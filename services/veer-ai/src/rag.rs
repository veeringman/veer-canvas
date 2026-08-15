//! Veer AI RAG — Okapi BM25 (b=0.78) + hashed mini-embeddings + title boost + MMR.
//!
//! Designed for colony knowledge bases on small EC2 hosts: no ONNX/Torch download,
//! fixed-size hashed n-gram vectors (CPU-only, ~µs per doc) fuse with BM25 via RRF
//! so short, on-topic passages beat long keyword-accident paragraphs.

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

/// Classic Okapi BM25 length normalization — tuned slightly higher than 0.75
/// so longer Info Centre sections don't drown shorter FAQ / dues snippets.
pub const BM25_B: f64 = 0.78;
pub const BM25_K1: f64 = 1.35;
pub const TITLE_FIELD_BOOST: f64 = 2.4;
pub const DEFAULT_MMR_LAMBDA: f64 = 0.72;
/// Signed hashing trick dimension — small enough for 1GB EC2, strong enough to separate topics.
pub const EMBED_DIM: usize = 384;
pub const RRF_K: f64 = 40.0;

static TOKEN_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[a-z0-9]+").expect("token re"));

static STOPWORDS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was",
        "were", "be", "been", "being", "it", "this", "that", "with", "as", "by", "from",
        "at", "into", "about", "over", "after", "before", "between", "through", "during",
        "above", "below", "up", "down", "out", "off", "again", "further", "then", "once",
        "here", "there", "when", "where", "why", "how", "all", "any", "both", "each",
        "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "can", "will", "just", "should", "now", "do",
        "does", "did", "have", "has", "had", "i", "me", "my", "we", "our", "you", "your",
        "he", "she", "they", "them", "their", "what", "which", "who", "whom", "please",
        "tell", "know", "want", "need", "could", "would", "may", "might",
    ]
    .into_iter()
    .collect()
});

/// Lightweight RWA / colony synonym expansion (query-side only).
static SYNONYMS: Lazy<HashMap<&'static str, &'static [&'static str]>> = Lazy::new(|| {
    let mut m: HashMap<&'static str, &'static [&'static str]> = HashMap::new();
    m.insert("dues", &["maintenance", "subscription", "arrears", "outstanding", "balance", "levy"]);
    m.insert("maintenance", &["dues", "subscription", "levy"]);
    m.insert("ec", &["committee", "executive", "office", "bearer", "president", "secretary", "treasurer"]);
    m.insert("committee", &["ec", "executive", "officebearer"]);
    m.insert("bylaws", &["bye", "laws", "rules", "regulations", "constitution"]);
    m.insert("bye", &["bylaws", "laws", "rules"]);
    m.insert("laws", &["bylaws", "rules", "act"]);
    m.insert("parking", &["vehicle", "pass", "gate", "adhoc", "staff"]);
    m.insert("pass", &["parking", "vehicle", "gate"]);
    m.insert("noc", &["objection", "certificate", "noobjection"]);
    m.insert("objection", &["noc", "certificate"]);
    m.insert("nodues", &["dues", "certificate", "clearance"]);
    m.insert("water", &["supply", "tank", "pipeline"]);
    m.insert("garbage", &["sanitation", "waste", "cleanliness"]);
    m.insert("tenant", &["tenancy", "occupant", "renter"]);
    m.insert("delegate", &["member", "household", "primary"]);
    m.insert("info", &["information", "document", "centre", "center", "folder"]);
    m.insert("information", &["info", "document", "centre"]);
    m.insert("notice", &["circular", "announcement", "bulletin"]);
    m.insert("concern", &["grievance", "complaint", "mailbox"]);
    m.insert("campaign", &["pledge", "funding", "drive", "plantation", "contribution"]);
    m.insert("marketplace", &["buy", "sell", "listing", "classified", "ad"]);
    m.insert("directory", &["plot", "resident", "owner", "delegate", "section"]);
    m.insert("proceedings", &["minutes", "mom", "meeting", "agm"]);
    m.insert("meeting", &["proceedings", "minutes", "mom"]);
    m.insert("bank", &["upi", "ifsc", "account", "payment", "dues"]);
    m.insert("upi", &["bank", "payment", "dues"]);
    m.insert("works", &["project", "maintenance", "event", "contractor"]);
    m
});

#[derive(Debug, Clone, Deserialize)]
pub struct RagDoc {
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub source: String,
    /// Optional multiplicative prior from the host app (intent / personal boost).
    #[serde(default = "one")]
    pub boost: f64,
}

fn one() -> f64 {
    1.0
}

#[derive(Debug, Deserialize)]
pub struct RagRetrieveRequest {
    pub query: String,
    #[serde(default)]
    pub docs: Vec<RagDoc>,
    #[serde(default = "default_k")]
    pub k: usize,
    #[serde(default)]
    pub site_id: Option<String>,
    /// Extra free-text to expand the query (prior turns, plot context).
    #[serde(default)]
    pub expand_with: Option<String>,
    #[serde(default = "default_mmr")]
    pub mmr_lambda: f64,
    #[serde(default = "default_b")]
    pub bm25_b: f64,
    #[serde(default = "default_k1")]
    pub bm25_k1: f64,
    /// Drop candidates below this fraction of the top BM25 score (0 disables).
    #[serde(default = "default_min_frac")]
    pub min_score_frac: f64,
}

fn default_k() -> usize {
    8
}
fn default_mmr() -> f64 {
    DEFAULT_MMR_LAMBDA
}
fn default_b() -> f64 {
    BM25_B
}
fn default_k1() -> f64 {
    BM25_K1
}
fn default_min_frac() -> f64 {
    0.12
}

#[derive(Debug, Serialize)]
pub struct RagHit {
    pub id: String,
    pub title: String,
    pub text: String,
    pub source: String,
    pub score: f64,
    pub bm25: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub embed: Option<f64>,
}

#[derive(Debug, Serialize)]
pub struct RagRetrieveResponse {
    pub ok: bool,
    pub engine: String,
    pub version: String,
    pub query_tokens: Vec<String>,
    pub hits: Vec<RagHit>,
    pub docs_scored: usize,
}

pub fn tokenize(text: &str) -> Vec<String> {
    TOKEN_RE
        .find_iter(&(text.to_lowercase()))
        .map(|m| m.as_str().to_string())
        .filter(|t| t.len() > 1 && !STOPWORDS.contains(t.as_str()))
        .collect()
}

fn expand_tokens(tokens: &[String]) -> Vec<String> {
    let mut out: Vec<String> = Vec::with_capacity(tokens.len() * 2);
    let mut seen = HashSet::new();
    for t in tokens {
        if seen.insert(t.clone()) {
            out.push(t.clone());
        }
        if let Some(syns) = SYNONYMS.get(t.as_str()) {
            for s in *syns {
                let s = (*s).to_string();
                if seen.insert(s.clone()) {
                    out.push(s);
                }
            }
        }
    }
    out
}

fn term_freqs(tokens: &[String]) -> HashMap<String, u32> {
    let mut tf = HashMap::new();
    for t in tokens {
        *tf.entry(t.clone()).or_insert(0u32) += 1;
    }
    tf
}

fn jaccard(a: &HashSet<String>, b: &HashSet<String>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let inter = a.intersection(b).count() as f64;
    let union = a.union(b).count() as f64;
    if union <= 0.0 {
        0.0
    } else {
        inter / union
    }
}

/// FNV-1a 64-bit — stable across platforms for the hashing trick.
fn fnv1a64(bytes: &[u8]) -> u64 {
    let mut hash: u64 = 0xcbf29ce484222325;
    for b in bytes {
        hash ^= u64::from(*b);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

/// Signed hashing-trick embedding over unigrams + bigrams (+ char 3-grams for short tokens).
pub fn hashed_embed(tokens: &[String]) -> Vec<f32> {
    let mut v = vec![0.0_f32; EMBED_DIM];
    let bump = |v: &mut [f32], key: &str, weight: f32| {
        let h = fnv1a64(key.as_bytes());
        let idx = (h as usize) % EMBED_DIM;
        let sign = if (h >> 63) & 1 == 0 { 1.0_f32 } else { -1.0_f32 };
        v[idx] += sign * weight;
    };
    for t in tokens {
        bump(&mut v, t, 1.0);
        // Char trigrams help plot codes / short Hindi transliterations survive tokenization noise.
        if t.len() >= 3 && t.len() <= 12 {
            let bytes = t.as_bytes();
            for w in bytes.windows(3) {
                bump(&mut v, &format!("c3:{}", String::from_utf8_lossy(w)), 0.35);
            }
        }
    }
    for w in tokens.windows(2) {
        bump(&mut v, &format!("{}_{}", w[0], w[1]), 0.75);
    }
    // L2 normalize
    let mut norm = 0.0_f32;
    for x in &v {
        norm += x * x;
    }
    norm = norm.sqrt();
    if norm > 1e-9 {
        for x in &mut v {
            *x /= norm;
        }
    }
    v
}

fn cosine(a: &[f32], b: &[f32]) -> f64 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let mut dot = 0.0_f64;
    for (x, y) in a.iter().zip(b.iter()) {
        dot += f64::from(*x) * f64::from(*y);
    }
    // vectors are L2-normalized → cosine == dot
    dot.clamp(-1.0, 1.0)
}

fn mmr_select(
    candidates: &[(f64, f64, f64, &RagDoc, HashSet<String>)],
    k: usize,
    lambda: f64,
) -> Vec<usize> {
    let n = candidates.len();
    if n == 0 || k == 0 {
        return vec![];
    }
    let mut selected: Vec<usize> = Vec::with_capacity(k.min(n));
    let mut remaining: HashSet<usize> = (0..n).collect();

    // Seed with best fused score.
    let mut best_i = 0usize;
    let mut best_s = f64::NEG_INFINITY;
    for (i, (score, _, _, _, _)) in candidates.iter().enumerate() {
        if *score > best_s {
            best_s = *score;
            best_i = i;
        }
    }
    selected.push(best_i);
    remaining.remove(&best_i);

    while selected.len() < k && !remaining.is_empty() {
        let mut pick = None;
        let mut pick_val = f64::NEG_INFINITY;
        for &i in &remaining {
            let (rel, _, _, _, toks) = &candidates[i];
            let mut max_sim = 0.0_f64;
            for &j in &selected {
                let sim = jaccard(toks, &candidates[j].4);
                if sim > max_sim {
                    max_sim = sim;
                }
            }
            let val = lambda * rel - (1.0 - lambda) * max_sim;
            if val > pick_val {
                pick_val = val;
                pick = Some(i);
            }
        }
        if let Some(i) = pick {
            selected.push(i);
            remaining.remove(&i);
        } else {
            break;
        }
    }
    selected
}

pub fn retrieve(req: &RagRetrieveRequest) -> RagRetrieveResponse {
    let k = req.k.clamp(1, 40);
    let b = if req.bm25_b > 0.0 && req.bm25_b < 1.0 {
        req.bm25_b
    } else {
        BM25_B
    };
    let k1 = if req.bm25_k1 > 0.0 { req.bm25_k1 } else { BM25_K1 };
    let mmr_lambda = req.mmr_lambda.clamp(0.0, 1.0);
    let min_frac = req.min_score_frac.clamp(0.0, 0.9);

    // Keep for request tracing / multi-tenant logs later.
    let _site = req.site_id.as_deref().unwrap_or("");
    let _ = _site;

    let mut q_raw = tokenize(&req.query);
    if let Some(extra) = &req.expand_with {
        q_raw.extend(tokenize(extra));
    }
    let q_tokens = expand_tokens(&q_raw);
    if q_tokens.is_empty() || req.docs.is_empty() {
        return RagRetrieveResponse {
            ok: true,
            engine: "bm25+ngram+mmr".into(),
            version: env!("CARGO_PKG_VERSION").into(),
            query_tokens: q_tokens,
            hits: vec![],
            docs_scored: 0,
        };
    }

    let q_embed = hashed_embed(&q_tokens);

    // Build corpus stats.
    let mut doc_tokens: Vec<Vec<String>> = Vec::with_capacity(req.docs.len());
    let mut doc_lens: Vec<f64> = Vec::with_capacity(req.docs.len());
    let mut df: HashMap<String, u32> = HashMap::new();
    let mut title_tfs: Vec<HashMap<String, u32>> = Vec::with_capacity(req.docs.len());

    for doc in &req.docs {
        let body = tokenize(&format!("{} {}", doc.title, doc.text));
        let title = tokenize(&doc.title);
        let mut seen = HashSet::new();
        for t in &body {
            if seen.insert(t.clone()) {
                *df.entry(t.clone()).or_insert(0u32) += 1;
            }
        }
        doc_lens.push(body.len().max(1) as f64);
        title_tfs.push(term_freqs(&title));
        doc_tokens.push(body);
    }

    let n = req.docs.len() as f64;
    let avgdl = doc_lens.iter().sum::<f64>() / n.max(1.0);

    let mut idf: HashMap<String, f64> = HashMap::new();
    for t in &q_tokens {
        let dfi = *df.get(t).unwrap_or(&0) as f64;
        // BM25+ style smooth IDF
        let val = ((n - dfi + 0.5) / (dfi + 0.5) + 1.0).ln().max(0.0);
        idf.insert(t.clone(), val);
    }

    // (bm25_prior, bm25_raw, embed_cos, doc, token_set)
    let mut scored: Vec<(f64, f64, f64, &RagDoc, HashSet<String>)> =
        Vec::with_capacity(req.docs.len());
    for (i, doc) in req.docs.iter().enumerate() {
        let tf = term_freqs(&doc_tokens[i]);
        let dl = doc_lens[i];
        let mut bm25 = 0.0_f64;
        for t in &q_tokens {
            let freq = *tf.get(t).unwrap_or(&0) as f64;
            if freq <= 0.0 {
                continue;
            }
            let idf_t = *idf.get(t).unwrap_or(&0.0);
            let denom = freq + k1 * (1.0 - b + b * (dl / avgdl.max(1.0)));
            bm25 += idf_t * (freq * (k1 + 1.0)) / denom.max(1e-9);
            // Title field boost
            let t_freq = *title_tfs[i].get(t).unwrap_or(&0) as f64;
            if t_freq > 0.0 {
                bm25 += idf_t * TITLE_FIELD_BOOST * (t_freq / (t_freq + 1.0));
            }
        }
        if bm25 <= 0.0 {
            continue;
        }
        let prior = if doc.boost.is_finite() && doc.boost > 0.0 {
            doc.boost
        } else {
            1.0
        };
        let bm25_prior = bm25 * prior;
        let emb = cosine(&q_embed, &hashed_embed(&doc_tokens[i]));
        let set: HashSet<String> = doc_tokens[i].iter().cloned().collect();
        scored.push((bm25_prior, bm25, emb, doc, set));
    }

    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    // Soft relevance gate: drop weak BM25 tails before embedding fusion.
    if min_frac > 0.0 && !scored.is_empty() {
        let top = scored[0].0;
        let floor = top * min_frac;
        scored.retain(|row| row.0 >= floor);
    }
    // Cap candidates before fusion / MMR for speed on small hosts.
    if scored.len() > 64 {
        scored.truncate(64);
    }

    // Rank by BM25 and by embedding cosine, then RRF-fuse.
    let mut bm25_order: Vec<usize> = (0..scored.len()).collect();
    bm25_order.sort_by(|&i, &j| {
        scored[j]
            .0
            .partial_cmp(&scored[i].0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let mut emb_order: Vec<usize> = (0..scored.len()).collect();
    emb_order.sort_by(|&i, &j| {
        scored[j]
            .2
            .partial_cmp(&scored[i].2)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let mut bm25_rank = vec![0usize; scored.len()];
    let mut emb_rank = vec![0usize; scored.len()];
    for (r, &i) in bm25_order.iter().enumerate() {
        bm25_rank[i] = r;
    }
    for (r, &i) in emb_order.iter().enumerate() {
        emb_rank[i] = r;
    }

    // (fused, bm25_raw, embed, doc, tokens)
    let mut fused: Vec<(f64, f64, f64, &RagDoc, HashSet<String>)> =
        Vec::with_capacity(scored.len());
    for (i, row) in scored.into_iter().enumerate() {
        let rrf = 1.0 / (RRF_K + bm25_rank[i] as f64) + 1.0 / (RRF_K + emb_rank[i] as f64);
        // Prefer embedding when BM25 is noisy on long docs: slight embed tilt.
        let fused_score = rrf + 0.08 * row.2.max(0.0);
        fused.push((fused_score, row.1, row.2, row.3, row.4));
    }
    fused.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));

    let selected = mmr_select(&fused, k, mmr_lambda);
    let hits = selected
        .into_iter()
        .filter_map(|i| fused.get(i))
        .map(|(score, bm25, emb, doc, _)| RagHit {
            id: doc.id.clone(),
            title: doc.title.clone(),
            text: doc.text.clone(),
            source: doc.source.clone(),
            score: (*score * 1000.0).round() / 1000.0,
            bm25: (*bm25 * 1000.0).round() / 1000.0,
            embed: Some((*emb * 1000.0).round() / 1000.0),
        })
        .collect::<Vec<_>>();

    RagRetrieveResponse {
        ok: true,
        engine: "bm25+ngram+mmr".into(),
        version: env!("CARGO_PKG_VERSION").into(),
        query_tokens: q_tokens,
        hits,
        docs_scored: fused.len(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn req(query: &str, docs: Vec<RagDoc>, k: usize) -> RagRetrieveRequest {
        RagRetrieveRequest {
            query: query.into(),
            docs,
            k,
            site_id: None,
            expand_with: None,
            mmr_lambda: DEFAULT_MMR_LAMBDA,
            bm25_b: BM25_B,
            bm25_k1: BM25_K1,
            min_score_frac: 0.12,
        }
    }

    #[test]
    fn finds_dues_chunk() {
        let res = retrieve(&req(
            "what are my outstanding dues",
            vec![
                RagDoc {
                    id: "1".into(),
                    title: "Parking FAQ".into(),
                    text: "Gate passes are issued at the main gate.".into(),
                    source: "faq".into(),
                    boost: 1.0,
                },
                RagDoc {
                    id: "2".into(),
                    title: "My dues".into(),
                    text: "Plot A-12 has outstanding maintenance dues of Rs 4500.".into(),
                    source: "dues".into(),
                    boost: 2.0,
                },
            ],
            2,
        ));
        assert!(!res.hits.is_empty());
        assert_eq!(res.hits[0].id, "2");
        assert_eq!(res.engine, "bm25+ngram+mmr");
    }

    #[test]
    fn prefers_topical_short_passage_over_long_keyword_dump() {
        let long_noise = format!(
            "Directory plot A-1 Section North Owner Alice. Directory plot A-2 Section North Owner Bob. \
             Directory plot A-3 Section South Owner Carol. Many plots and residents and owners and sections. \
             Also mentions maintenance once in passing. {}",
            "plot owner resident section ".repeat(40)
        );
        let res = retrieve(&req(
            "plantation campaign pledge how to contribute",
            vec![
                RagDoc {
                    id: "noise".into(),
                    title: "Directory overview".into(),
                    text: long_noise,
                    source: "directory".into(),
                    boost: 1.0,
                },
                RagDoc {
                    id: "camp".into(),
                    title: "Campaign: Green plantation drive".into(),
                    text: "Active plantation campaign. Residents may pledge funds or contribute via UPI. Deadline 30 Sep.".into(),
                    source: "campaigns".into(),
                    boost: 1.0,
                },
            ],
            2,
        ));
        assert_eq!(res.hits[0].id, "camp");
    }

    #[test]
    fn hashed_embed_is_normalized() {
        let v = hashed_embed(&tokenize("outstanding maintenance dues balance"));
        assert_eq!(v.len(), EMBED_DIM);
        let norm: f32 = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-3);
    }

    #[test]
    fn cosine_self_is_one() {
        let v = hashed_embed(&tokenize("bye laws society rules"));
        assert!((cosine(&v, &v) - 1.0).abs() < 1e-5);
    }
}
