"""Transport errors for graph services and optional hosting adapters."""

from fastapi import HTTPException

from atlas_graph.runtime import host


def service_error_to_http(error: Exception) -> HTTPException:
    mapper = host().errors
    if mapper is not None:
        return mapper(error)
    from atlas_graph.services.sharing_service import CollaborationGatedError

    if isinstance(error, HTTPException):
        return error
    if isinstance(error, CollaborationGatedError):
        return HTTPException(status_code=402, detail={"code": "collaboration_gated", "message": str(error)})
    if isinstance(error, PermissionError):
        return HTTPException(status_code=403, detail="Access denied")
    if not isinstance(error, ValueError):
        raise error
    message = str(error)
    text = message.lower()
    code = 403 if "access denied" in text or "does not belong to you" in text else 404 if "not found" in text else 409 if "revision mismatch" in text or "409 conflict" in text else 413 if "exceeds" in text else 400
    return HTTPException(status_code=code, detail=message)

