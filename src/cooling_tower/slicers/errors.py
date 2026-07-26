class SlicerError(RuntimeError):
    """Base error for slicer discovery and execution."""


class UnsupportedSlicerExecutableError(SlicerError):
    """The selected executable does not belong to a supported adapter."""


class SlicerVerificationTimeoutError(SlicerError):
    """A safe product/version probe did not finish in time."""


class SlicerProcessError(SlicerError):
    """A slicer process failed or produced no usable result."""


class SlicerProcessCancelled(SlicerProcessError):
    """A running slicer process was cancelled."""


class SlicerSourceMutationError(SlicerProcessError):
    """A slicer-owned source file changed during a protected operation."""
