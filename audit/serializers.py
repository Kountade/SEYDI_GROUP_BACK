from rest_framework import serializers
from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.email', read_only=True)
    action_display = serializers.CharField(
        source='get_action_display', read_only=True)

    class Meta:
        model = AuditLog
        fields = '__all__'
