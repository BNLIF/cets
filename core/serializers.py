from rest_framework import serializers
from .models import FEMB


class ItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(max_length=100)


class FEMBSerializer(serializers.ModelSerializer):
    class Meta:
        model = FEMB
        fields = '__all__'
