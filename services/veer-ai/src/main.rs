//! Veer AI — native Rust AI platform sidecar.
//!
//! v0.79: moderation + BM25 + hashed n-gram mini-embeddings + MMR RAG.
//!
//!   GET  /health
//!   POST /v1/moderate   { "text": "...", "image_url": "...", "site_id": "..." }
//!   POST /v1/rag/retrieve
//!        { "query": "...", "docs": [...], "k": 8, "expand_with": "...", "site_id": "..." }
//!
//! Bind: VEER_AI_BIND (default 127.0.0.1:8095)

mod moderate;
mod rag;

use axum::{
    routing::{get, post},
    Json, Router,
};
use moderate::{moderate as run_moderate, ModerateRequest, ModerateResponse};
use rag::{retrieve as run_retrieve, RagRetrieveRequest, RagRetrieveResponse};
use std::net::SocketAddr;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;
use tracing_subscriber::EnvFilter;

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "ok": true,
        "service": "veer-ai",
        "version": env!("CARGO_PKG_VERSION"),
        "endpoints": ["/health", "/v1/moderate", "/v1/rag/retrieve"],
        "rag": {
            "engine": "bm25+ngram+mmr",
            "bm25_b": rag::BM25_B,
            "bm25_k1": rag::BM25_K1,
            "embed_dim": rag::EMBED_DIM,
            "embed": "hashed-ngram",
        }
    }))
}

async fn moderate_handler(Json(req): Json<ModerateRequest>) -> Json<ModerateResponse> {
    Json(run_moderate(&req))
}

async fn rag_retrieve_handler(Json(req): Json<RagRetrieveRequest>) -> Json<RagRetrieveResponse> {
    Json(run_retrieve(&req))
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .init();

    let bind = std::env::var("VEER_AI_BIND").unwrap_or_else(|_| "127.0.0.1:8095".into());
    let addr: SocketAddr = bind
        .parse()
        .unwrap_or_else(|_| SocketAddr::from(([127, 0, 0, 1], 8095)));

    let app = Router::new()
        .route("/health", get(health))
        .route("/v1/moderate", post(moderate_handler))
        .route("/v1/rag/retrieve", post(rag_retrieve_handler))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http());

    tracing::info!("veer-ai {} listening on {addr}", env!("CARGO_PKG_VERSION"));
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("bind veer-ai");
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .expect("serve veer-ai");
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    tracing::info!("veer-ai shutting down");
}
