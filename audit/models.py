from django.db import models

# Create your models here.
from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey


class AuditLog(models.Model):
    ACTION_CHOICES = (
        ('create', 'Création'),
        ('update', 'Modification'),
        ('delete', 'Suppression'),
        ('login', 'Connexion'),
        ('logout', 'Déconnexion'),
        ('export', 'Export'),
        ('import', 'Import'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(
        max_length=100, blank=True, null=True)  # ex: 'Sale', 'Customer'
    object_id = models.CharField(max_length=255, null=True, blank=True) 
    object_repr = models.CharField(
        max_length=200, blank=True, null=True)  # représentation textuelle
    # {"field": {"old": "v1", "new": "v2"}}
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['user', 'action']),
            models.Index(fields=['model_name']),
        ]

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.action} - {self.model_name}"
