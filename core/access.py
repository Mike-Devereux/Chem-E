from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import User


def _has_supervisor_access(user):
    return user.role in {User.Role.SUPERVISOR, User.Role.ADMINISTRATOR}


def _has_administrator_access(user):
    return user.role == User.Role.ADMINISTRATOR


def _role_required(predicate):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not predicate(request.user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


supervisor_required = _role_required(_has_supervisor_access)
administrator_required = _role_required(_has_administrator_access)


class RoleRequiredMixin(AccessMixin):
    def has_role_permission(self):
        return False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not self.has_role_permission():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class SupervisorRequiredMixin(RoleRequiredMixin):
    def has_role_permission(self):
        return _has_supervisor_access(self.request.user)


class AdministratorRequiredMixin(RoleRequiredMixin):
    def has_role_permission(self):
        return _has_administrator_access(self.request.user)
