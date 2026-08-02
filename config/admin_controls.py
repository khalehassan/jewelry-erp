class ProtectedFromAdminDeletionMixin:
    """Keep audit-sensitive records out of every Django admin delete path."""

    def has_delete_permission(self, request, obj=None):
        return False
