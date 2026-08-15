//! Content moderation heuristics for Veer AI v1.
//!
//! Deterministic lexicon + scoring. Designed so a model backend can replace
//! `score_text` later without changing the HTTP contract.

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize)]
#[allow(dead_code)]
pub struct ModerateRequest {
    pub text: Option<String>,
    pub image_url: Option<String>,
    pub lang: Option<String>,
    pub site_id: Option<String>,
    pub context: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LabelScore {
    pub label: String,
    pub score: f32,
}

#[derive(Debug, Clone, Serialize)]
pub struct ModerateResponse {
    pub ok: bool,
    pub action: String,
    pub labels: Vec<LabelScore>,
    pub reasons: Vec<String>,
    pub engine: String,
    pub version: String,
}

static WORD: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?i)[a-z0-9']+").expect("word re"));

fn obscenity_terms() -> &'static [&'static str] {
    &[
        "fuck", "fucking", "fucker", "shit", "bitch", "asshole", "cunt", "dickhead",
        "motherfucker", "bastard", "slut", "whore", "porn", "xxx", "nude", "nudes",
        "chod", "chutiya", "madarchod", "behenchod", "bhosdi", "randi", "gaand",
    ]
}

fn hate_terms() -> &'static [&'static str] {
    &[
        "kill all", "death to", "gas the", "rape you", "rape her", "lynch",
        "terrorist scum", "go back to", "subhuman", "nigger", "kike", "paki",
        "muslims should die", "hindus should die", "christians should die",
    ]
}

fn harassment_terms() -> &'static [&'static str] {
    &[
        "i will kill you", "kill yourself", "kys", "doxx", "dox you",
        "your address is", "rape threat",
    ]
}

fn spam_terms() -> &'static [&'static str] {
    &[
        "crypto giveaway", "free bitcoin", "click this link now", "whatsapp me for loan",
        "guaranteed returns", "earn $$$",
    ]
}

fn contains_phrase(hay: &str, phrase: &str) -> bool {
    hay.contains(phrase)
}

fn word_hits(hay: &str, terms: &[&str]) -> Vec<String> {
    let lower = hay.to_lowercase();
    let words: Vec<&str> = WORD.find_iter(&lower).map(|m| m.as_str()).collect();
    let mut hits = Vec::new();
    for term in terms {
        if term.contains(' ') {
            if contains_phrase(&lower, term) {
                hits.push((*term).to_string());
            }
            continue;
        }
        if words.iter().any(|w| w == term || w.starts_with(&format!("{term}'"))) {
            hits.push((*term).to_string());
        }
    }
    hits
}

fn clamp01(v: f32) -> f32 {
    v.clamp(0.0, 1.0)
}

pub fn score_text(text: &str) -> ModerateResponse {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return ModerateResponse {
            ok: true,
            action: "allow".into(),
            labels: vec![],
            reasons: vec![],
            engine: "veer-ai-rules".into(),
            version: env!("CARGO_PKG_VERSION").into(),
        };
    }

    let mut labels = Vec::new();
    let mut reasons = Vec::new();

    let hate = word_hits(trimmed, hate_terms());
    if !hate.is_empty() {
        let score = clamp01(0.55 + 0.15 * hate.len() as f32);
        labels.push(LabelScore {
            label: "hate".into(),
            score,
        });
        reasons.push(format!("hate lexicon: {}", hate.join(", ")));
    }

    let obscenity = word_hits(trimmed, obscenity_terms());
    if !obscenity.is_empty() {
        let score = clamp01(0.45 + 0.12 * obscenity.len() as f32);
        labels.push(LabelScore {
            label: "obscenity".into(),
            score,
        });
        reasons.push(format!("obscenity lexicon: {}", obscenity.join(", ")));
    }

    let harassment = word_hits(trimmed, harassment_terms());
    if !harassment.is_empty() {
        let score = clamp01(0.6 + 0.15 * harassment.len() as f32);
        labels.push(LabelScore {
            label: "harassment".into(),
            score,
        });
        reasons.push(format!("harassment lexicon: {}", harassment.join(", ")));
    }

    let spam = word_hits(trimmed, spam_terms());
    if !spam.is_empty() {
        let score = clamp01(0.4 + 0.1 * spam.len() as f32);
        labels.push(LabelScore {
            label: "spam".into(),
            score,
        });
        reasons.push(format!("spam lexicon: {}", spam.join(", ")));
    }

    // Caps / shouty abuse signal
    let letters: Vec<char> = trimmed.chars().filter(|c| c.is_alphabetic()).collect();
    if letters.len() >= 12 {
        let upper = letters.iter().filter(|c| c.is_uppercase()).count();
        if (upper as f32) / (letters.len() as f32) > 0.75 && !obscenity.is_empty() {
            if let Some(l) = labels.iter_mut().find(|l| l.label == "obscenity") {
                l.score = clamp01(l.score + 0.1);
            }
            reasons.push("shouting + obscenity".into());
        }
    }

    let max_score = labels
        .iter()
        .map(|l| l.score)
        .fold(0.0_f32, f32::max);

    let action = if max_score >= 0.78 {
        "block"
    } else if max_score >= 0.48 {
        "flag"
    } else {
        "allow"
    };

    ModerateResponse {
        ok: true,
        action: action.into(),
        labels,
        reasons,
        engine: "veer-ai-rules".into(),
        version: env!("CARGO_PKG_VERSION").into(),
    }
}

pub fn moderate(req: &ModerateRequest) -> ModerateResponse {
    let mut resp = score_text(req.text.as_deref().unwrap_or(""));
    if req.image_url.as_deref().unwrap_or("").trim().is_empty() {
        return resp;
    }
    // Image pipeline placeholder — keep contract stable for vision models later.
    resp.reasons
        .push("image_url present; vision check not enabled in v1".into());
    resp
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clean_text_allows() {
        let r = score_text("Good morning Mandi, pool is open today.");
        assert_eq!(r.action, "allow");
    }

    #[test]
    fn obscenity_flags_or_blocks() {
        let r = score_text("you fucking idiot");
        assert!(r.action == "flag" || r.action == "block");
        assert!(r.labels.iter().any(|l| l.label == "obscenity"));
    }

    #[test]
    fn hate_phrase_blocks() {
        let r = score_text("we should kill all of them now");
        // "kill all" is in hate list
        assert!(r.action == "flag" || r.action == "block");
    }
}
