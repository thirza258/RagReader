from rest_framework import serializers

class QuerySerializer(serializers.Serializer):
    USER = serializers.CharField()
    QUERY = serializers.CharField()

class InsertURLSerializer(serializers.Serializer):
    USER = serializers.CharField()
    URL = serializers.URLField()

class InsertDataSerializer(serializers.Serializer):
    USER = serializers.CharField()
    FILE = serializers.FileField()

class DeepAnalysisSerializer(serializers.Serializer):
    USER = serializers.CharField()
    QUERY = serializers.CharField()

class InsertTextSerializer(serializers.Serializer):
    USER = serializers.CharField()
    TEXT = serializers.CharField()

# Long enough for any passphrase; a cap keeps a huge body from becoming a
# slow hash.
MAX_PASSWORD_LENGTH = 1024


class SignUpSerializer(serializers.Serializer):
    EMAIL = serializers.EmailField(max_length=254)
    USERNAME = serializers.CharField(max_length=255)
    # Optional only so legacy clients keep their response shape; without it
    # no token is issued.
    PASSWORD = serializers.CharField(
        required=False, write_only=True, trim_whitespace=False, max_length=MAX_PASSWORD_LENGTH,
    )


class SignInSerializer(serializers.Serializer):
    # Either one identifies the account; each is matched as a username first,
    # then as an email.
    USERNAME = serializers.CharField(required=False, max_length=255)
    EMAIL = serializers.CharField(required=False, max_length=254)
    PASSWORD = serializers.CharField(write_only=True, trim_whitespace=False, max_length=MAX_PASSWORD_LENGTH)

    def validate(self, attrs):
        if not attrs.get("USERNAME") and not attrs.get("EMAIL"):
            raise serializers.ValidationError({"USERNAME": ["Enter your username or email."]})
        return attrs
