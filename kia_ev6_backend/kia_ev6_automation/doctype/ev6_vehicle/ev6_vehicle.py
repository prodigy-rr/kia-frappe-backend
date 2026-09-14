from frappe.model.document import Document

class EV6Vehicle(Document):
    def validate(self):
        if not self.vin:
            self.vin = self.name
        self.format_vehicle_name()

    def format_vehicle_name(self):
        """Dynamically formats vehicle name e.g. 'Kia EV6 Wind AWD' or 'Kia EV6 AWD'."""
        parts = ["Kia EV6"]
        if self.trim:
            parts.append(self.trim.strip())
        if self.drivetrain:
            parts.append(self.drivetrain.strip())
        self.vehicle_name = " ".join(parts)
