from .schemas import TaskViewResponse


class InMemoryTaskViewStore:
    def __init__(self) -> None:
        self._views: dict[str, TaskViewResponse] = {}

    def save(self, view: TaskViewResponse) -> TaskViewResponse:
        self._views[view.id] = view
        return view

    def get(self, view_id: str) -> TaskViewResponse | None:
        return self._views.get(view_id)

    def clear(self) -> None:
        self._views.clear()


store = InMemoryTaskViewStore()

