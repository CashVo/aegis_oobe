# aegis/web/core/pagination.py
# Pagination helpers for Mission Control APIs

from typing import Generic, TypeVar, Optional, List
from pydantic import BaseModel, Field, computed_field
from fastapi import Query

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Standard pagination parameters."""

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=50, ge=1, le=500, description="Items per page")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class CursorPaginationParams(BaseModel):
    """Cursor-based pagination for large datasets."""

    cursor: Optional[str] = Field(default=None, description="Opaque cursor for next page")
    limit: int = Field(default=50, ge=1, le=500, description="Items per page")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response envelope."""

    items: List[T]
    page: int
    page_size: int
    total_items: Optional[int] = None
    total_pages: Optional[int] = None
    has_next: bool
    has_prev: bool

    @computed_field
    @property
    def next_page(self) -> Optional[int]:
        return self.page + 1 if self.has_next else None

    @computed_field
    @property
    def prev_page(self) -> Optional[int]:
        return self.page - 1 if self.has_prev else None

    @classmethod
    def create(
        cls,
        items: List[T],
        page: int,
        page_size: int,
        total_items: Optional[int] = None,
    ) -> "PaginatedResponse[T]":
        has_next = False
        has_prev = page > 1
        total_pages = None

        if total_items is not None:
            total_pages = (total_items + page_size - 1) // page_size
            has_next = page < total_pages

        return cls(
            items=items,
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
        )


def get_pagination_params(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
) -> PaginationParams:
    """FastAPI dependency for pagination parameters."""
    return PaginationParams(page=page, page_size=page_size)