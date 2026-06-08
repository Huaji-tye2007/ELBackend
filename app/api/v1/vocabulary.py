"""Vocabulary endpoints: upload, list, and lookup.

Ref: AGENTS.md §10 — endpoint table.
Exception translation: AGENTS.md §15.2.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas import VocabularyUploadRequest, VocabularyUploadResponse
from app.core.dependencies import get_user_vocab_storage, get_vocabulary_preprocessor
from app.core.exceptions import ValidationError
from app.db.storage import JSONStorage
from app.models.vocabulary import UserVocabulary, VocabularyItem

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=VocabularyUploadResponse, status_code=200)
async def upload_vocabulary(
    request: VocabularyUploadRequest,
    storage: JSONStorage[UserVocabulary] = Depends(get_user_vocab_storage),
    preprocessor=Depends(get_vocabulary_preprocessor),
) -> VocabularyUploadResponse:
    """Upload a word list and initialize FSRS cards for each entry.

    Delegates to VocabularyPreprocessor.preprocess(), then persists
    the resulting UserVocabulary via storage.save().

    Returns the count of vocabulary items created.
    """
    try:
        raw_items: list[dict[str, str]] = [
            {"word": item.word, "meaning": item.meaning} for item in request.items
        ]
        uv: UserVocabulary = preprocessor.preprocess(
            user_id=request.user_id, raw_items=raw_items
        )
        storage.save(uv)
        return VocabularyUploadResponse(count=len(uv.vocabulary))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("", response_model=UserVocabulary)
async def get_all_vocabulary(
    storage: JSONStorage[UserVocabulary] = Depends(get_user_vocab_storage),
) -> UserVocabulary:
    """Return the complete UserVocabulary for the current user.

    Loads the persisted vocabulary file. If the file does not exist
    (cold start), returns an empty vocabulary.
    """
    try:
        return storage.load()
    except FileNotFoundError:
        return UserVocabulary(user_id="default")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{item_id}", response_model=VocabularyItem)
async def get_vocabulary_item(
    item_id: str,
    storage: JSONStorage[UserVocabulary] = Depends(get_user_vocab_storage),
) -> VocabularyItem:
    """Return a single vocabulary item by its ``item_id``.

    Returns 404 if the item_id does not exist in the vocabulary.
    """
    try:
        vocab = storage.load()
        return vocab.vocab_index[item_id]
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Vocabulary item {item_id!r} not found"
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Vocabulary item {item_id!r} not found"
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


__all__ = ["router"]
