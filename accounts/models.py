from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('ADMIN', 'Administrator'),
        ('MANAGER', 'Store Manager'),
        ('CASHIER', 'Cashier / POS Operator'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='CASHIER')
    phone = models.CharField(max_length=20, blank=True, null=True)
    assigned_warehouse = models.CharField(max_length=100, blank=True, null=True, default='Main Warehouse (Central)')

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def is_admin(self):
        return self.role == 'ADMIN' or self.user.is_superuser

    @property
    def is_manager(self):
        return self.role in ['ADMIN', 'MANAGER'] or self.user.is_superuser

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance, role='ADMIN' if instance.is_superuser else 'CASHIER')
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()
