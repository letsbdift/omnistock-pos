from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('super_admin', 'Super Administrator'),
        ('admin', 'Operational Administrator'),
        ('repair_desk_manager', 'Repair Desk Manager'),
        ('user', 'Sales Staff / Cashier'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    employee_id = models.CharField(max_length=30, blank=True, null=True, unique=True)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='user')
    is_cash_handler = models.BooleanField(default=False, help_text="Strictly 1 active Cash Handler across the system")
    phone = models.CharField(max_length=20, blank=True, null=True)
    assigned_branch = models.CharField(
        max_length=100, 
        default='Mumbai Bandra', 
        help_text="Branch scope: Mumbai Bandra, Delhi Connaught, Bengaluru Koramangala, etc."
    )
    reward_points = models.IntegerField(default=0, help_text="Staff incentive reward points")
    is_active_staff = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        # Single Super Admin Invariant
        if self.role == 'super_admin':
            existing = UserProfile.objects.filter(role='super_admin')
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError("Single Super Admin Invariant Violated: Exactly ONE Super Administrator can exist in the system.")
        
        # Single Active Cash Handler Invariant
        if self.is_cash_handler:
            existing_ch = UserProfile.objects.filter(is_cash_handler=True)
            if self.pk:
                existing_ch = existing_ch.exclude(pk=self.pk)
            if existing_ch.exists():
                raise ValidationError("Single Active Cash Handler Invariant Violated: Exactly ONE user can hold the designated Cash Handler role.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        ch_flag = " [Cash Handler]" if self.is_cash_handler else ""
        return f"{self.user.username} ({self.get_role_display()}{ch_flag})"

    @property
    def is_super_admin(self):
        return self.role == 'super_admin' or self.user.is_superuser

    @property
    def is_admin(self):
        return self.role in ['super_admin', 'admin'] or self.user.is_superuser

    @property
    def is_repair_manager(self):
        return self.role in ['super_admin', 'admin', 'repair_desk_manager'] or self.user.is_superuser

    @property
    def can_view_cost_and_profit(self):
        # Strict Cost Price Concealment Invariant: Only Super Admin, Admin, and Cash Handler can view cost & profit margins
        if self.user.is_superuser or self.role in ['super_admin', 'admin']:
            return True
        if self.is_cash_handler:
            return True
        return False

    @property
    def can_direct_override_price(self):
        return self.role in ['super_admin', 'admin'] or self.user.is_superuser

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        is_first_super = (instance.is_superuser or instance.username in ['user_admin_arif', 'admin'])
        UserProfile.objects.create(
            user=instance,
            employee_id=f"EMP-ADM-001" if instance.username == 'user_admin_arif' else f"EMP-{instance.id:03d}",
            role='super_admin' if is_first_super else 'user',
            is_cash_handler=False
        )
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()
