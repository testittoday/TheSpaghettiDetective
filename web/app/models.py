from datetime import datetime
from django.db import models
from jsonfield import JSONField
from django.contrib.auth.models import AbstractUser, UserManager
from django.utils.translation import ugettext_lazy as _
from simple_history.models import HistoricalRecords
import os
import json

from lib import redis
from lib.utils import dict_or_none

class UserManager(UserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a User with the given email and password."""
        if not email:
            raise ValueError('The given email must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField(_('email address'), unique=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()


class Printer(models.Model):
    CANCEL = 'CANCEL'
    PAUSE = 'PAUSE'
    NONE = 'NONE'

    ACTION_ON_FAILURE = (
        (NONE, 'Just email me.'),
        (PAUSE, 'Pause the print and email me.'),
        (CANCEL, 'Cancel the print and email me (not available during beta testing).'),
    )

    name = models.CharField(max_length=200, null=False)
    auth_token = models.CharField(max_length=28, unique=True, null=False, blank=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=False)
    current_print_filename = models.CharField(max_length=1000, null=True, blank=True)
    current_print_started_at = models.DateTimeField(null=True)
    current_print_alerted_at = models.DateTimeField(null=True)
    current_print_alert_muted = models.BooleanField(default=False)
    action_on_failure = models.CharField(
        max_length=10,
        choices=ACTION_ON_FAILURE,
        default=PAUSE,
    )
    tools_off_on_pause = models.BooleanField(default=True)
    bed_off_on_pause = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    if os.environ.get('ENALBE_HISTORY', '') == 'True':
        history = HistoricalRecords()

    @property
    def status(self):
        status_data = redis.printer_status_get(self.id)
        if 'seconds_left' in status_data:
            status_data['seconds_left'] = int(status_data['seconds_left'])
        return dict_or_none(status_data)

    @property
    def pic(self):
        pic_data = redis.printer_pic_get(self.id)
        if 'p' in pic_data:
            pic_data['p'] = float(pic_data['p'])
        return dict_or_none(pic_data)

    def set_current_print(self, filename):
        if filename != self.current_print_filename:
            self.current_print_filename = filename
            self.current_print_started_at = datetime.now()
            self.save()

    def unset_current_print(self):
        if self.current_print_filename is not None:
            self.current_print_filename = None
            self.current_print_started_at = None
            self.current_print_alerted_at = None
            self.current_print_alert_muted = False
            self.save()

    def set_alert(self):
        if not self.current_print_alerted_at:
            self.current_print_alerted_at = datetime.now()
            self.save()

    def clear_alert(self):
        self.current_print_alerted_at = None
        self.save()

    def queue_octoprint_command(self, command, args={}, clear_alert=False):
        PrinterCommand.objects.create(printer=self, command=json.dumps({'cmd': command, 'args': args}), status=PrinterCommand.PENDING)
        if clear_alert:
            self.clear_alert()

    def __str__(self):
        return self.name


class PrinterCommand(models.Model):
    PENDING = 'PENDING'
    SENT = 'SENT'

    COMMAND_STATUSES = (
        (PENDING, 'pending'),
        (SENT, 'sent'),
    )

    printer = models.ForeignKey(Printer, on_delete=models.CASCADE, null=False)
    command = models.CharField(max_length=2000, null=False, blank=False)
    status = models.CharField(
        max_length=10,
        choices=COMMAND_STATUSES,
        default=PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PublicTimelapse(models.Model):
    title = models.CharField(max_length=500)
    priority = models.IntegerField(null=False, default=1000000)
    video_url = models.CharField(max_length=2000, null=False, blank=False)
    poster_url = models.CharField(max_length=2000, null=False, blank=False)
    creator_name = models.CharField(max_length=500, null=False, blank=False)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    frame_p = JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
