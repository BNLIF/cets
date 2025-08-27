from django.db import models
from decouple import config
import os


class FEMB(models.Model):
    version = models.CharField(max_length=20, default="IO-1865-1K")
    serial_number = models.CharField(max_length=10)
    status = models.CharField(max_length=20, default="testing")
    last_update = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [["version", "serial_number"]]

    def __str__(self):
        return f"FEMB: {self.version}/{self.serial_number}"


class FE(models.Model):
    serial_number = models.CharField(max_length=20, unique=True)
    status = models.CharField(max_length=20, default="testing")
    tray_id = models.CharField(max_length=20)
    last_update = models.DateTimeField(auto_now=True)
    femb = models.ForeignKey(FEMB, on_delete=models.CASCADE, null=True, blank=True)
    femb_pos = models.CharField(max_length=2, null=True, blank=True)  # F1-4, B1-4

    def rts(self):
        rts_dir = config("RTS_DIR")
        rts_dir = os.path.join(rts_dir, self.tray_id, "results")
        try:
            filelist = os.listdir(rts_dir)
        except FileNotFoundError:
            print(f"Directory {rts_dir} not found.")
            return []

        parsed_files = []
        for filename in filelist:
            if filename.startswith(self.serial_number) and filename.endswith(".csv"):
                try:
                    # Strip serial number and extension
                    parts_str = filename[len(self.serial_number) + 1 : -4]
                    parts = parts_str.split("_")
                    if len(parts) == 4:
                        parsed_files.append(
                            {
                                "filename": filename,
                                "serial_number": self.serial_number,
                                "timestamp": parts[0],
                                "tray": parts[1],
                                "socket": parts[2],
                                "temperature": parts[3],
                            }
                        )
                except IndexError:
                    # Ignore files that don't match the expected format
                    pass

        parsed_files.sort(key=lambda x: x["temperature"])
        parsed_files.sort(key=lambda x: x["timestamp"], reverse=True)

        return parsed_files

    def __str__(self):
        return f"LArASIC: {self.serial_number}"


class ADC(models.Model):
    serial_number = models.CharField(max_length=20, unique=True)
    status = models.CharField(max_length=20, default="testing")
    tray_id = models.CharField(max_length=20, null=True, blank=True)
    last_update = models.DateTimeField(auto_now=True)
    femb = models.ForeignKey(FEMB, on_delete=models.CASCADE, null=True, blank=True)
    femb_pos = models.CharField(max_length=2, null=True, blank=True)  # F1-4, B1-4

    def __str__(self):
        return f"ColdADC: {self.serial_number}"


class COLDATA(models.Model):
    serial_number = models.CharField(max_length=20, unique=True)
    status = models.CharField(max_length=20, default="testing")
    tray_id = models.CharField(max_length=20, null=True, blank=True)
    last_update = models.DateTimeField(auto_now=True)
    femb = models.ForeignKey(FEMB, on_delete=models.CASCADE, null=True, blank=True)
    femb_pos = models.CharField(max_length=2, null=True, blank=True)  # F1-2

    def __str__(self):
        return f"COLDATA: {self.serial_number}"
