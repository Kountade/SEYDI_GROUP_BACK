from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in, user_logged_out
from .models import AuditLog


@receiver(post_save)
def log_save(sender, instance, created, **kwargs):
    if sender.__name__ == 'AuditLog':
        return
    action = 'create' if created else 'update'
    AuditLog.objects.create(
        user=getattr(instance, 'created_by', None) or getattr(
            instance, 'updated_by', None) or None,
        action=action,
        model_name=sender.__name__,
        object_id=str(instance.pk) if instance.pk else None,
        object_repr=str(instance),
        changes={},
    )


@receiver(post_delete)
def log_delete(sender, instance, **kwargs):
    if sender.__name__ == 'AuditLog':
        return
    AuditLog.objects.create(
        user=None,
        action='delete',
        model_name=sender.__name__,
        object_id=str(instance.pk) if instance.pk else None,
        object_repr=str(instance),
        changes={},
    )


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    AuditLog.objects.create(
        user=user,
        action='login',
        model_name='User',
        object_repr=user.username,
    )


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    if user:
        AuditLog.objects.create(
            user=user,
            action='logout',
            model_name='User',
            object_repr=user.username,
        )
