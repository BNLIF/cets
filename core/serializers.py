from rest_framework import serializers
from .models import FEMB, FembTest


class FembTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = FembTest
        fields = "__all__"


class FEMBSerializer(serializers.ModelSerializer):
    fembtest_set = FembTestSerializer(many=True, read_only=True)

    class Meta:
        model = FEMB
        fields = ["id", "version", "serial_number", "status", "fembtest_set"]
