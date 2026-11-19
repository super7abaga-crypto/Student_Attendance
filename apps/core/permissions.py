from rest_framework.permissions import BasePermission, SAFE_METHODS
from .models import User
from .services import user_can_access


class StaffRolePermission(BasePermission):
    allowed_roles = {User.Role.SUPER_ADMIN, User.Role.CAMPUS_ADMIN, User.Role.MENTOR, User.Role.OFFICER}
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_superuser or request.user.role in self.allowed_roles))


class CampusScopePermission(BasePermission):
    def has_object_permission(self, request, view, obj):
        campus = obj if hasattr(obj, "user_access") else getattr(obj, "campus", None)
        if campus is None:
            return False
        if request.method in SAFE_METHODS:
            return user_can_access(request.user, campus)
        return user_can_access(request.user, campus, manage=True)
