from rest_framework import serializers
from .models import FEMB, FEMB_TEST


class FEMBTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = FEMB_TEST
        fields = "__all__"


class FEMBSerializer(serializers.ModelSerializer):
    femb_test_set = FEMBTestSerializer(many=True, read_only=True)

    class Meta:
        model = FEMB
        fields = ["id", "version", "serial_number", "status", "femb_test_set"]
