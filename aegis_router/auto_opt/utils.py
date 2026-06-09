import logging
from dataclasses import dataclass

log = logging.getLogger("auto_opt")
log.setLevel(logging.INFO)

@dataclass
class BetaBinomialMetric:
    alpha: int = 1
    beta: int = 1

    @property
    def loss(self) -> float:
        return self.beta / (self.alpha + self.beta)

    def observe(self, success: bool) -> None:
        if success:
            self.alpha += 1
        else:
            self.beta += 1
