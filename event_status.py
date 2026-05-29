STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_CANCELLED = "cancelled"
STATUS_ENDED = "ended"

FINISHED_STATUSES = (STATUS_CANCELLED, STATUS_ENDED)

STATUS_LABELS = {
    STATUS_PENDING: "Предстоящий",
    STATUS_ACTIVE: "Идёт сейчас",
    STATUS_CANCELLED: "Отменён",
    STATUS_ENDED: "Завершён",
}
