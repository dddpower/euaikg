"""Document loading and text splitting with token-aware chunking."""

from pathlib import Path
from transformers import AutoTokenizer
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
import config

_tokenizer = None


def _get_tokenizer():
    """Lazy-load the tokenizer (matches the vLLM model's tokenizer)."""
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = AutoTokenizer.from_pretrained(config.VLLM_MODEL_ID)
    return _tokenizer


def num_tokens_from_string(text: str) -> int:
    """Count tokens using the model tokenizer."""
    return len(_get_tokenizer().encode(text))


def load_and_chunk(source_file: Path = None) -> list:
    """
    Load a text file and split it into token-aware chunks.

    Returns a list of Document objects with metadata:
        - source: file path
        - page: 1-based chunk index
    """
    path = source_file or config.DOCUMENT_PATH
    text = path.read_text(encoding="utf-8")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        length_function=num_tokens_from_string,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_text(text)

    documents = [
        Document(
            page_content=chunk,
            metadata={"source": str(path), "page": idx + 1},
        )
        for idx, chunk in enumerate(chunks)
    ]
    print(f"[chunking] Split complete: {len(documents)} documents")
    return documents
