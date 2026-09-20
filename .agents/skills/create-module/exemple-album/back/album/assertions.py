from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.user.models import User
from core.authorize.assertions import BaseAssertion
from .models import Album

class AlbumOwnerAssertion(BaseAssertion):
    """
    Asserts that the current user is the owner of the album.
    Assumes the route has an 'id' path parameter.
    """
    async def assert_(self, user: User, request: Request, db: AsyncSession) -> bool:
        # Get Album ID from path parameters
        album_id_str = request.path_params.get("id")
        if not album_id_str:
            # Should not happen if used on a route with {id}
            return False
            
        try:
            album_id = int(album_id_str)
        except ValueError:
            return False

        # Query Album to check ownership (created_by)
        # Assuming Base model has created_by field (Integer, User ID)
        stmt = select(Album).where(Album.id == album_id)
        result = await db.execute(stmt)
        album = result.scalar_one_or_none()

        if not album:
            # If album doesn't exist, we can either return False (403) or let the 
            # route handler return 404. Returning False here hides existence.
            # Security-wise, False is safer.
            return False
            
        # Check if user is the creator
        # Use created_by_id if that's the column name, or created_by if it's the relationship ID
        # Based on style guide: "created_by => User.id or NULL"
        return album.created_by == user.id
