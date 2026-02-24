"""Graph extraction: vLLM primary pass + Gemini fallback retry."""

import pickle
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

from tqdm import tqdm
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_core.load import dumps

import config


def _make_vllm_transformer():
    """Create an LLMGraphTransformer backed by local vLLM."""
    llm = ChatOpenAI(
        base_url=config.VLLM_BASE_URL,
        api_key="dummy",
        model=config.VLLM_MODEL_ID,
        temperature=0,
    )
    return LLMGraphTransformer(
        llm=llm,
        node_properties=["description"],
        relationship_properties=["description"],
    )


def _make_gemini_transformer():
    """Create an LLMGraphTransformer backed by Google Gemini."""
    llm = ChatGoogleGenerativeAI(
        model=config.GEMINI_EXTRACTION_MODEL,
        google_api_key=config.GOOGLE_API_KEY,
        temperature=0,
    )
    return LLMGraphTransformer(
        llm=llm,
        node_properties=["description"],
        relationship_properties=["description"],
    )


def _save_graphs(save_dir: Path, page_no: int, graphs, suffix: str = ""):
    """Persist graphs as pkl + jsonl for a single page."""
    tag = f"_{suffix}" if suffix else ""
    with (save_dir / f"graph_page_{page_no:03}{tag}.pkl").open("wb") as f:
        pickle.dump(graphs, f)
    with (save_dir / f"graph_page_{page_no:03}{tag}.jsonl").open("w", encoding="utf-8") as f:
        for g in graphs:
            f.write(dumps(g) + "\n")


def _save_all(save_dir: Path, all_graphs):
    """Persist the combined graph_all.pkl and graph_all.jsonl."""
    with (save_dir / "graph_all.pkl").open("wb") as f:
        pickle.dump(all_graphs, f)
    with (save_dir / "graph_all.jsonl").open("w", encoding="utf-8") as f:
        for g in all_graphs:
            f.write(dumps(g) + "\n")


def extract_graphs(documents: list) -> Path:
    """
    Run full extraction pipeline: vLLM primary pass, Gemini retry for failures.

    Returns the path to graph_all.pkl.

    Resumability: if graph_all.pkl already exists, skip entirely.
    """
    save_dir = config.GRAPH_CACHE_DIR
    save_dir.mkdir(exist_ok=True)
    all_pkl = save_dir / "graph_all.pkl"

    # ── Resumability checkpoint ──
    if all_pkl.exists():
        print("[extraction] graph_all.pkl exists, skipping extraction phase.")
        return all_pkl

    # ── vLLM primary pass ──
    transformer = _make_vllm_transformer()

    def convert_one(doc):
        page_no = doc.metadata["page"]
        t0 = time.perf_counter()
        graphs = transformer.convert_to_graph_documents(
            [doc], config={"max_concurrency": 1}
        )
        _save_graphs(save_dir, page_no, graphs)
        return page_no, graphs, time.perf_counter() - t0

    all_graphs = []
    failed = []
    start = time.perf_counter()
    print(f"[extraction] Starting vLLM extraction for {len(documents)} chunks...")

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        futures = {
            executor.submit(convert_one, doc): doc.metadata["page"]
            for doc in documents
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc="vLLM extraction"):
            page = futures[future]
            try:
                _, graphs, _ = future.result(timeout=config.EXTRACTION_TIMEOUT)
                all_graphs.extend(graphs)
            except TimeoutError:
                failed.append(page)
            except Exception:
                failed.append(page)

    print(
        f"[extraction] vLLM pass done: {len(all_graphs)} graphs, "
        f"{len(failed)} failed ({time.perf_counter() - start:.1f}s)"
    )

    # ── Gemini fallback for failed pages ──
    if failed:
        print(f"[extraction] Retrying {len(failed)} failed chunks with Gemini...")
        gemini_transformer = _make_gemini_transformer()

        def convert_gemini(doc):
            page_no = doc.metadata["page"]
            t0 = time.perf_counter()
            graphs = gemini_transformer.convert_to_graph_documents(
                [doc], config={"max_concurrency": 1, "max_tokens": 2048}
            )
            _save_graphs(save_dir, page_no, graphs, suffix="gemini")
            return page_no, graphs, time.perf_counter() - t0

        retry_docs = [d for d in documents if d.metadata["page"] in failed]
        still_failed = []

        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            futures = {
                executor.submit(convert_gemini, doc): doc.metadata["page"]
                for doc in retry_docs
            }
            for future in tqdm(
                as_completed(futures), total=len(futures), desc="Gemini retry"
            ):
                page = futures[future]
                try:
                    page_no, graphs, elapsed = future.result(
                        timeout=config.EXTRACTION_TIMEOUT
                    )
                    all_graphs.extend(graphs)
                    print(f"  [retry] page {page_no:03} OK ({elapsed:.2f}s)")
                except TimeoutError:
                    print(f"  [retry] page {page:03} timeout")
                    still_failed.append(page)
                except Exception as e:
                    print(f"  [retry] page {page:03} failed: {e}")
                    still_failed.append(page)

        if still_failed:
            print(f"[extraction] Still failed after Gemini retry: {sorted(still_failed)}")
        else:
            print("[extraction] All pages recovered via Gemini.")

    # ── Save combined result ──
    _save_all(save_dir, all_graphs)
    print(f"[extraction] Saved {len(all_graphs)} total graph documents to {all_pkl}")
    return all_pkl
