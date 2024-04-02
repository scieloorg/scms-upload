from rest_framework import serializers

from core.models import PressRelease


class PressReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = PressRelease
        fields = '__all__'
