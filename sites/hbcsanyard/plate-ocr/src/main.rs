//! Native plate OCR sidecar.
//!
//! Reads an image from stdin (JPEG/PNG), finds a plate-shaped band, upscales it,
//! and runs Tesseract with an A–Z / 0–9 whitelist. Prints JSON:
//! `{ "engine": "rust+tesseract", "candidates": ["HP33A1234"], "text": "..." }`
//!
//! Build on the server:
//!   cargo build --release --manifest-path plate-ocr/Cargo.toml
//!   install -m 755 target/release/plate-ocr data/bin/plate-ocr
//!
//! The Python lookup prefers this binary when present; otherwise it uses Tesseract CLI.

use std::io::{self, Read, Write};
use std::process::{Command, Stdio};

use image::imageops::{self, FilterType};
use image::{DynamicImage, GenericImageView, GrayImage, Luma};

fn main() {
    let mut raw = Vec::new();
    if let Err(err) = io::stdin().read_to_end(&mut raw) {
        fail(&format!("stdin: {err}"));
    }
    if raw.is_empty() {
        fail("empty image");
    }
    let img = match image::load_from_memory(&raw) {
        Ok(img) => img,
        Err(err) => fail(&format!("decode: {err}")),
    };
    let crops = plate_crops(&img);
    let mut texts = Vec::new();
    for crop in crops {
        if let Some(text) = tesseract_line(&crop) {
            if !text.trim().is_empty() {
                texts.push(text);
            }
        }
    }
    let blob = texts.join(" ");
    let candidates = extract_plates(&blob);
    let body = serde_json::json!({
        "engine": "rust+tesseract",
        "candidates": candidates,
        "text": blob.chars().take(400).collect::<String>(),
    });
    let _ = writeln!(io::stdout(), "{body}");
}

fn fail(msg: &str) -> ! {
    let body = serde_json::json!({ "engine": "rust+tesseract", "candidates": [], "text": "", "error": msg });
    let _ = writeln!(io::stderr(), "{msg}");
    let _ = writeln!(io::stdout(), "{body}");
    std::process::exit(1);
}

fn plate_crops(img: &DynamicImage) -> Vec<GrayImage> {
    let (w, h) = img.dimensions();
    if w < 40 || h < 20 {
        return vec![to_plate_gray(img)];
    }
    let rels: &[(f32, f32)] = if (h as f32) / (w.max(1) as f32) < 0.45 {
        &[(0.0, 1.0)]
    } else {
        &[(0.35, 0.45), (0.15, 0.40), (0.50, 0.40)]
    };
    let mut out = Vec::new();
    for &(top_frac, height_frac) in rels {
        let band_h = ((h as f32) * height_frac).round().max(32.0) as u32;
        let mut top = ((h as f32) * top_frac).round() as u32;
        if top + band_h > h {
            top = h.saturating_sub(band_h);
        }
        let crop = img.crop_imm(0, top, w, band_h);
        out.push(to_plate_gray(&crop));
        if out.len() >= 3 {
            break;
        }
    }
    out
}

fn to_plate_gray(img: &DynamicImage) -> GrayImage {
    let gray = img.to_luma8();
    let target_h = 140u32;
    let scale = target_h as f32 / gray.height().max(1) as f32;
    let target_w = ((gray.width() as f32) * scale).round().max(80.0) as u32;
    let resized = imageops::resize(&gray, target_w, target_h, FilterType::Lanczos3);
    autocontrast(&resized)
}

fn autocontrast(src: &GrayImage) -> GrayImage {
    let mut min_v = 255u8;
    let mut max_v = 0u8;
    for p in src.pixels() {
        min_v = min_v.min(p.0[0]);
        max_v = max_v.max(p.0[0]);
    }
    let span = (max_v - min_v).max(1) as f32;
    let mut out = GrayImage::new(src.width(), src.height());
    for (x, y, p) in src.enumerate_pixels() {
        let v = (((p.0[0] - min_v) as f32 / span) * 255.0).round() as u8;
        out.put_pixel(x, y, Luma([v]));
    }
    out
}

fn tesseract_line(img: &GrayImage) -> Option<String> {
    let path = std::env::temp_dir().join(format!(
        "plate-ocr-{}-{}.png",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    ));
    DynamicImage::ImageLuma8(img.clone())
        .save(&path)
        .ok()?;
    let output = Command::new("tesseract")
        .args([
            path.to_str()?,
            "stdout",
            "--psm",
            "7",
            "-l",
            "eng",
            "-c",
            "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .ok();
    let _ = std::fs::remove_file(&path);
    let output = output?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).into_owned())
}

fn extract_plates(text: &str) -> Vec<String> {
    let mut compact: String = text
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .map(|c| c.to_ascii_uppercase())
        .collect();
    compact = compact.replace("INDIA", "").replace("IND", "");
    let patterns = [
        regex_plate,
    ];
    let mut found = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for cap in patterns.iter().flat_map(|p| p(&compact)) {
        if (6..=12).contains(&cap.len()) && seen.insert(cap.clone()) {
            found.push(cap);
        }
    }
    if (6..=12).contains(&compact.len()) && seen.insert(compact.clone()) {
        found.push(compact);
    }
    found
}

fn regex_plate(compact: &str) -> Vec<String> {
    // AA 00 AAA 0000 / 22 BH 0000 AA / AA 000000
    let bytes = compact.as_bytes();
    let mut out = Vec::new();
    let n = bytes.len();
    for i in 0..n {
        // 2 letters + 1-2 digits + 1-3 letters + 3-4 digits
        if i + 7 > n {
            break;
        }
        if !bytes[i].is_ascii_alphabetic() || !bytes[i + 1].is_ascii_alphabetic() {
            continue;
        }
        let mut j = i + 2;
        let mut digits = 0;
        while j < n && bytes[j].is_ascii_digit() && digits < 2 {
            j += 1;
            digits += 1;
        }
        if digits < 1 {
            continue;
        }
        let mut letters = 0;
        while j < n && bytes[j].is_ascii_alphabetic() && letters < 3 {
            j += 1;
            letters += 1;
        }
        if letters < 1 {
            continue;
        }
        let mut tail = 0;
        while j < n && bytes[j].is_ascii_digit() && tail < 4 {
            j += 1;
            tail += 1;
        }
        if tail >= 3 {
            out.push(compact[i..j].to_string());
        }
    }
    out
}
