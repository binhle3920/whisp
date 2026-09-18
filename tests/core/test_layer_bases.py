import pytest

from whisp.inputs.base import BaseEmailInput
from whisp.outputs.base import BaseNotificationOutput
from whisp.processors.base import BaseEmailProcessor


class IncompleteInput(BaseEmailInput):
    pass


class IncompleteProcessor(BaseEmailProcessor):
    pass


class IncompleteOutput(BaseNotificationOutput):
    pass


@pytest.mark.parametrize(
    "implementation",
    [IncompleteInput, IncompleteProcessor, IncompleteOutput],
)
def test_incomplete_layer_implementation_cannot_be_instantiated(implementation) -> None:
    with pytest.raises(TypeError, match="abstract"):
        implementation()
