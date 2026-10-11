from abc import ABC, abstractmethod


class Store(ABC):
    @abstractmethod
    def save(self, record): ...
