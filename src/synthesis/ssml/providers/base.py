from abc import ABC, abstractmethod

class SSMLRenderer(ABC):
    @abstractmethod
    def render(self, plan: list[dict]) -> str:
        pass
