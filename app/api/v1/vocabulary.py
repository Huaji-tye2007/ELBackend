"""Vocabulary endpoints: upload, list, and lookup.

Ref: AGENTS.md §10 — endpoint table.
Exception translation: AGENTS.md §15.2.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas import VocabularyUploadRequest, VocabularyUploadResponse
from app.core.exceptions import ValidationError
from app.db.storage import JSONStorage
from app.models.vocabulary import UserVocabulary, VocabularyItem

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])


# ---------------------------------------------------------------------------
# Dependency stubs (will be migrated to app.core.dependencies — T18)
# ---------------------------------------------------------------------------


def get_user_vocabulary_storage() -> JSONStorage[UserVocabulary]:
    """Return a JSONStorage[UserVocabulary] instance.

    TODO(T18): Move to app.core.dependencies and inject Path from settings.
    """
    return JSONStorage(
        path=None,  # type: ignore[arg-type]  # placeholder — overridden in tests
        model=UserVocabulary,
    )


def get_vocabulary_preprocessor():
    """Return a VocabularyPreprocessor instance.

    TODO(T18): Move to app.core.dependencies and inject storage + ECDICT.
    """
    return None  # placeholder — overridden in tests


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=VocabularyUploadResponse, status_code=200)
async def upload_vocabulary(
    request: VocabularyUploadRequest,
    storage: JSONStorage[UserVocabulary] = Depends(get_user_vocabulary_storage),
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
        uv: UserVocabulary = preprocessor.preprocess(raw_items, user_id=request.user_id)
        storage.save(uv)
        return VocabularyUploadResponse(count=len(uv.vocabulary))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("", response_model=UserVocabulary)
async def get_all_vocabulary(
    storage: JSONStorage[UserVocabulary] = Depends(get_user_vocabulary_storage),
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
    storage: JSONStorage[UserVocabulary] = Depends(get_user_vocabulary_storage),
) -> VocabularyItem:
    """Look up a single VocabularyItem by its item_id.

    Raises:
        HTTPException(404): If the item_id is not found in the vocabulary.
    """
    try:
        uv = storage.load()
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Vocabulary item '{item_id}' not found"
        ) from None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    idx = uv.vocab_index
    if item_id not in idx:
        raise HTTPException(
            status_code=404, detail=f"Vocabulary item '{item_id}' not found"
        )
    return idx[item_id]


__all__ = ["router", "get_user_vocabulary_storage", "get_vocabulary_preprocessor"]
