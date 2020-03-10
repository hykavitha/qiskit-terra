# -*- coding: utf-8 -*-

# This code is part of Qiskit.
#
# (C) Copyright IBM 2020.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
Parametric pulse commands module. These are pulse commands which are described by a specified
parameterization.

If a backend supports parametric pulses, it will have the attribute
`backend.configuration().parametric_pulses`, which is a list of supported pulse shapes, such as
`['gaussian', 'gaussian_square', 'drag']`. A Pulse Schedule, using parametric pulses, which is
assembled for a backend which supports those pulses, will result in a Qobj which is dramatically
smaller than one which uses SamplePulses.

This module can easily be extended to describe more pulse shapes. The new class should:
  - have a descriptive name
  - be a well known and/or well described formula (include the formula in the class docstring)
  - take some parameters (at least `duration`) and validate them, if necessary
  - implement a `get_sample_pulse` method which returns a corresponding SamplePulse in the
    case that it is assembled for a backend which does not support it.

The new pulse must then be registered by the assembler in
`qiskit/qobj/converters/pulse_instruction.py:ParametricPulseShapes`
by following the existing pattern:
    class ParametricPulseShapes(Enum):
        gaussian = commands.Gaussian
        ...
        new_supported_pulse_name = commands.YourPulseCommandClass
"""
from abc import abstractmethod
from typing import Any, Callable, Dict, Optional
import math

import numpy as np

from qiskit.pulse.pulse_lib import gaussian, gaussian_square, drag, constant, continuous
from .sample_pulse import SamplePulse
from ..instructions import Instruction
from ..channels import PulseChannel
from ..exceptions import PulseError

from .pulse_command import PulseCommand

# pylint: disable=missing-docstring


class ParametricPulse(PulseCommand):
    """The abstract superclass for parametric pulses."""

    @abstractmethod
    def __init__(self, duration: int):
        """Create a parametric pulse and validate the input parameters.

        Args:
            duration: Pulse length in terms of the the sampling period `dt`.
        """
        super().__init__(duration=duration)
        self.validate_parameters()

    @abstractmethod
    def get_sample_pulse(self) -> SamplePulse:
        """Return a SamplePulse with samples filled according to the formula that the pulse
        represents and the parameter values it contains.
        """
        raise NotImplementedError

    @abstractmethod
    def validate_parameters(self) -> None:
        """
        Validate parameters.

        Raises:
            PulseError: If the parameters passed are not valid.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """Return a dictionary containing the pulse's parameters."""
        pass

    def to_instruction(self, channel: PulseChannel,
                       name: Optional[str] = None) -> 'ParametricInstruction':
        # pylint: disable=arguments-differ
        return ParametricInstruction(self, channel, name=name)

    def draw(self, dt: float = 1,
             style=None,
             filename: Optional[str] = None,
             interp_method: Optional[Callable] = None,
             scale: float = 1, interactive: bool = False,
             scaling: float = None):
        """Plot the pulse.

        Args:
            dt: Time interval of samples.
            style (Optional[PulseStyle]): A style sheet to configure plot appearance
            filename: Name required to save pulse image
            interp_method: A function for interpolation
            scale: Relative visual scaling of waveform amplitudes
            interactive: When set true show the circuit in a new window
                (this depends on the matplotlib backend being used supporting this)
            scaling: Deprecated, see `scale`

        Returns:
            matplotlib.figure: A matplotlib figure object of the pulse envelope
        """
        return self.get_sample_pulse().draw(dt=dt, style=style, filename=filename,
                                            interp_method=interp_method, scale=scale,
                                            interactive=interactive)


class Gaussian(ParametricPulse):
    """
    A truncated pulse envelope shaped according to the Gaussian function whose mean is centered at
    the center of the pulse (duration / 2):

    .. math::

        f(x) = amp * exp( -(1/2) * (x - duration/2)^2 / sigma^2) )  ,  0 <= x < duration
    """

    def __init__(self,
                 duration: int,
                 amp: complex,
                 sigma: float):
        """Initialize the gaussian pulse.

        Args:
            duration: Pulse length in terms of the the sampling period `dt`.
            amp: The amplitude of the Gaussian envelope.
            sigma: A measure of how wide or narrow the Gaussian peak is; described mathematically
                   in the class docstring.
        """
        self._amp = complex(amp)
        self._sigma = sigma
        super().__init__(duration=duration)

    @property
    def amp(self):
        return self._amp

    @property
    def sigma(self):
        return self._sigma

    def get_sample_pulse(self) -> SamplePulse:
        return gaussian(duration=self.duration, amp=self.amp,
                        sigma=self.sigma, zero_ends=False)

    def validate_parameters(self) -> None:
        if abs(self.amp) > 1.:
            raise PulseError("The amplitude norm must be <= 1, "
                             "found: {}".format(abs(self.amp)))
        if self.sigma <= 0:
            raise PulseError("Sigma must be greater than 0.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"duration": self.duration, "amp": self.amp, "sigma": self.sigma}

    def __repr__(self):
        return '{}(duration={}, amp={}, sigma={})' \
               ''.format(self.__class__.__name__, self.duration, self.amp, self.sigma)


class GaussianSquare(ParametricPulse):
    """
    A square pulse with a Gaussian shaped risefall on either side:

    .. math::

        risefall = (duration - width) / 2

        0 <= x < risefall

        f(x) = amp * exp( -(1/2) * (x - risefall/2)^2 / sigma^2) )

        risefall <= x < risefall + width

        f(x) = amp

        risefall + width <= x < duration

        f(x) = amp * exp( -(1/2) * (x - (risefall + width)/2)^2 / sigma^2) )
    """

    def __init__(self,
                 duration: int,
                 amp: complex,
                 sigma: float,
                 width: float):
        """Initialize the gaussian square pulse.

        Args:
            duration: Pulse length in terms of the the sampling period `dt`.
            amp: The amplitude of the Gaussian and of the square pulse.
            sigma: A measure of how wide or narrow the Gaussian risefall is; see the class
                   docstring for more details.
            width: The duration of the embedded square pulse.
        """
        self._amp = complex(amp)
        self._sigma = sigma
        self._width = width
        super().__init__(duration=duration)

    @property
    def amp(self):
        return self._amp

    @property
    def sigma(self):
        return self._sigma

    @property
    def width(self):
        return self._width

    def get_sample_pulse(self) -> SamplePulse:
        return gaussian_square(duration=self.duration, amp=self.amp,
                               width=self.width, sigma=self.sigma,
                               zero_ends=False)

    def validate_parameters(self) -> None:
        if abs(self.amp) > 1.:
            raise PulseError("The amplitude norm must be <= 1, "
                             "found: {}".format(abs(self.amp)))
        if self.sigma <= 0:
            raise PulseError("Sigma must be greater than 0.")
        if self.width < 0 or self.width >= self.duration:
            raise PulseError("The pulse width must be at least 0 and less than its duration.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"duration": self.duration, "amp": self.amp, "sigma": self.sigma,
                "width": self.width}

    def __repr__(self):
        return '{}(duration={}, amp={}, sigma={}, width={})' \
               ''.format(self.__class__.__name__, self.duration, self.amp, self.sigma, self.width)


class Drag(ParametricPulse):
    r"""The Derivative Removal by Adiabatic Gate (DRAG) pulse is a standard Gaussian pulse
    with an additional Gaussian derivative component. It is designed to reduce the frequency
    spectrum of a normal gaussian pulse near the :math:`|1\rangle` - :math:`|2\rangle` transition,
    reducing the chance of leakage to the :math:`|2\rangle` state.

    .. math::

        f(x) = Gaussian + 1j * beta * d/dx [Gaussian]
             = Gaussian + 1j * beta * (-(x - duration/2) / sigma^2) [Gaussian]

    where 'Gaussian' is:

    .. math::

        Gaussian(x, amp, sigma) = amp * exp( -(1/2) * (x - duration/2)^2 / sigma^2) )

    References:
        1. |citation1|_

        .. _citation1: https://link.aps.org/doi/10.1103/PhysRevA.83.012308

        .. |citation1| replace:: *Gambetta, J. M., Motzoi, F., Merkel, S. T. & Wilhelm, F. K.
           Analytic control methods for high-fidelity unitary operations
           in a weakly nonlinear oscillator. Phys. Rev. A 83, 012308 (2011).*

        2. |citation2|_

        .. _citation2: https://link.aps.org/doi/10.1103/PhysRevLett.103.110501

        .. |citation2| replace:: *F. Motzoi, J. M. Gambetta, P. Rebentrost, and F. K. Wilhelm
           Phys. Rev. Lett. 103, 110501 – Published 8 September 2009.*
    """

    def __init__(self,
                 duration: int,
                 amp: complex,
                 sigma: float,
                 beta: float):
        """Initialize the drag pulse.

        Args:
            duration: Pulse length in terms of the the sampling period `dt`.
            amp: The amplitude of the Drag envelope.
            sigma: A measure of how wide or narrow the Gaussian peak is; described mathematically
                   in the class docstring.
            beta: The correction amplitude.
        """
        self._amp = complex(amp)
        self._sigma = sigma
        self._beta = beta
        super().__init__(duration=duration)

    @property
    def amp(self):
        return self._amp

    @property
    def sigma(self):
        return self._sigma

    @property
    def beta(self):
        return self._beta

    def get_sample_pulse(self) -> SamplePulse:
        return drag(duration=self.duration, amp=self.amp, sigma=self.sigma,
                    beta=self.beta, zero_ends=False)

    def validate_parameters(self) -> None:
        if abs(self.amp) > 1.:
            raise PulseError("The amplitude norm must be <= 1, "
                             "found: {}".format(abs(self.amp)))
        if self.sigma <= 0:
            raise PulseError("Sigma must be greater than 0.")
        if isinstance(self.beta, complex):
            raise PulseError("Beta must be real.")
        # Check if beta is too large: the amplitude norm must be <=1 for all points
        if self.beta > self.sigma:
            # If beta <= sigma, then the maximum amplitude is at duration / 2, which is
            # already constrainted by self.amp <= 1

            # 1. Find the first maxima associated with the beta * d/dx gaussian term
            #    This eq is derived from solving for the roots of the norm of the drag function.
            #    There is a second maxima mirrored around the center of the pulse with the same
            #    norm as the first, so checking the value at the first x maxima is sufficient.
            argmax_x = (self.duration / 2
                        - (self.sigma / self.beta) * math.sqrt(self.beta ** 2 - self.sigma ** 2))
            if argmax_x < 0:
                # If the max point is out of range, either end of the pulse will do
                argmax_x = 0

            # 2. Find the value at that maximum
            max_val = continuous.drag(np.array(argmax_x), sigma=self.sigma,
                                      beta=self.beta, amp=self.amp, center=self.duration / 2)
            if abs(max_val) > 1.:
                raise PulseError("Beta is too large; pulse amplitude norm exceeds 1.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"duration": self.duration, "amp": self.amp, "sigma": self.sigma,
                "beta": self.beta}

    def __repr__(self):
        return '{}(duration={}, amp={}, sigma={}, beta={})' \
               ''.format(self.__class__.__name__, self.duration, self.amp, self.sigma, self.beta)


class ConstantPulse(ParametricPulse):
    """
    A simple constant pulse, with an amplitude value and a duration:

    .. math::

        f(x) = amp    ,  0 <= x < duration
        f(x) = 0      ,  elsewhere
    """

    def __init__(self,
                 duration: int,
                 amp: complex):
        """
        Initialize the constant-valued pulse.

        Args:
            duration: Pulse length in terms of the the sampling period `dt`.
            amp: The amplitude of the constant square pulse.
        """
        self._amp = complex(amp)
        super().__init__(duration=duration)

    @property
    def amp(self):
        return self._amp

    def get_sample_pulse(self) -> SamplePulse:
        return constant(duration=self.duration, amp=self.amp)

    def validate_parameters(self) -> None:
        if abs(self.amp) > 1.:
            raise PulseError("The amplitude norm must be <= 1, "
                             "found: {}".format(abs(self.amp)))

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"duration": self.duration, "amp": self.amp}

    def __repr__(self):
        return '{}(duration={}, amp={})'.format(self.__class__.__name__, self.duration, self.amp)


class ParametricInstruction(Instruction):
    """Instruction to drive a parametric pulse to an `PulseChannel`."""