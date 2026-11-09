"""drf-spectacular description of the workspace API's bearer tokens."""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class GuestTokenScheme(OpenApiAuthenticationExtension):
    target_class = "workspace.auth.GuestTokenAuthentication"
    name = "GuestToken"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "description": "Token returned by POST /api/v1/sign-up/ (data.token), sent as `Authorization: Bearer rr_…`.",
        }
