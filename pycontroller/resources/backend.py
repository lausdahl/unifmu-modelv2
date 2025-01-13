import logging
import os
import sys
from abc import ABC, abstractmethod
from enum import Enum, auto
import zmq

from schemas.fmi2_messages_pb2 import (
    Fmi2EmptyReturn,
    Fmi2Command,
    Fmi2StatusReturn,
    Fmi2FreeInstanceReturn,
    Fmi2SerializeFmuStateReturn,
    Fmi2GetRealReturn,
    Fmi2GetIntegerReturn,
    Fmi2GetBooleanReturn,
    Fmi2GetStringReturn,
)


class Fmi2Status:
    """
    Represents the status of an FMI2 FMU or the results of function calls.

    Values:
        * ok: all well
        * warning: an issue has arisen, but the computation can continue.
        * discard: an operation has resulted in invalid output, which must be discarded
        * error: an error has ocurred for this specific FMU instance.
        * fatal: an fatal error has ocurred which has corrupted ALL FMU instances.
        * pending: indicates that the FMu is doing work asynchronously, which can be retrived later.

    Notes:
        FMI section 2.1.3

    """

    ok = 0
    warning = 1
    discard = 2
    error = 3
    fatal = 4
    pending = 5


class Fmi2Causality(Enum):
    INPUT = 1  # Variables provided by the environment to the FMU.
    OUTPUT = 2  # Variables computed by the FMU and sent to the environment.
    PARAMETER = 3  # Variables with fixed values provided during initialization.
    CALCULATED_PARAMETER = 4  # Variables calculated from parameters during initialization.
    LOCAL = 5  # Internal variables used within the FMU, not exposed externally.
    INDEPENDENT = 6
    @classmethod
    def from_string(cls, value: str):
        # Convert string to the correct case
        value = value.strip().lower()
        for enum_value in cls:
            # Compare case-insensitively
            if enum_value.name.lower() == value:
                return enum_value
        raise ValueError(f"{value} is not a valid {cls.__name__} value")


class Fmi2Initial(Enum):
    exact = 1  # The value is fixed and cannot change.
    approx = 2  # The value will be calculated during initialization.
    CALCULATED = 3  # The value is free to change.
    @classmethod
    def from_string(cls, value: str):
        # Convert string to the correct case
        value = value.strip().lower()
        for enum_value in cls:
            # Compare case-insensitively
            if enum_value.name.lower() == value:
                return enum_value
        raise ValueError(f"{value} is not a valid {cls.__name__} value")


class Fmi2Variability(Enum):
    CONSTANT = 1  # The variable value does not change (e.g., pi, physical constants).
    FIXED = 2  # The variable value is fixed after initialization.
    TUNABLE = 3  # The variable value can change during initialization but not during simulation.
    DISCRETE = 4  # The variable value can change at discrete points in time.
    CONTINUOUS = 5  # The variable value changes continuously during simulation.
    @classmethod
    def from_string(cls, value: str):
        # Convert string to the correct case
        value = value.strip().lower()
        for enum_value in cls:
            # Compare case-insensitively
            if enum_value.name.lower() == value:
                return enum_value
        raise ValueError(f"{value} is not a valid {cls.__name__} value")


class Fmi2Port:

    def __init__(self, start_value=None, causality: Fmi2Causality = Fmi2Causality.INPUT,
                 initial: Fmi2Initial = Fmi2Initial.CALCULATED,
                 variability: Fmi2Variability = Fmi2Variability.DISCRETE):
        super().__init__()
        self.causality = causality
        self.initial = initial
        self.variability = variability
        self.value = start_value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value

    def __repr__(self):
        return f"{self.causality} {self.variability} {self.initial} {self.value}"


class ModelState(ABC):
    def __init__(self):
        self.value_reference_to_port = {}
        self.build()

    def build(self):
        self.value_reference_to_port = {
            idx: getattr(self, k)
            for idx, k in enumerate(self.__dict__.keys()) if isinstance(getattr(self, k), Fmi2Port)}

    def set_value(self, vr, value):
        return setattr(self.value_reference_to_port[vr], 'value', value)

    def get_value(self, vr):
        return getattr(self.value_reference_to_port[vr], 'value')


    def write_model_description(self, ports,path='md.xml'):
        with open(path, 'w') as f:
            f.write("""<?xml version='1.0' encoding='utf-8'?>
        <fmiModelDescription fmiVersion="2.0" modelName="unifmu" guid="77236337-210e-4e9c-8f2c-c1a0677db21b" author="Christian Møldrup Legaard" generationDateAndTime="2020-10-23T19:51:25Z" variableNamingConvention="flat" generationTool="unifmu">
          <CoSimulation modelIdentifier="unifmu" needsExecutionTool="true" canNotUseMemoryManagementFunctions="false" canHandleVariableCommunicationStepSize="true" />
          <LogCategories>
            <Category name="logStatusWarning" />
            <Category name="logStatusDiscard" />
            <Category name="logStatusError" />
            <Category name="logStatusFatal" />
            <Category name="logStatusPending" />
            <Category name="logAll" />
          </LogCategories>
            <ModelVariables>
        """)
            for idx, p in enumerate(ports):
                f.write(f'\t\t<!--Index of variable = "{idx + 1}"-->\n')
                f.write(
                    f'\t\t<ScalarVariable name="{p[1]}" valueReference="{p[0]}" variability="{str(p[2].variability.name.lower())}" causality="{str(p[2].causality.name.lower())}" ')
                if p[2].value:
                    f.write('>\n')
                    f.write(f'\t\t\t<Boolean start="{str(p[2].value)}" />\n')
                    f.write(f'\t\t</ScalarVariable>\n')
                else:
                    f.write('/>\n')
            f.write('''\t</ModelVariables>\n\t<ModelStructure>''')

            outputs = [f'<Unknown index="{idx + 1}" dependencies="" />' for idx, p in enumerate(ports) if
                       p[2].causality == Fmi2Causality.OUTPUT]
            f.write(f'\n\t\t<Outputs>\n\t\t\t' + "\n\t\t\t".join(outputs) + "\n\t\t</Outputs>")
            f.write(f'\n\t\t<InitialUnknowns>\n\t\t\t' + "\n\t\t\t".join(outputs) + "\n\t\t</InitialUnknowns>")
            f.write("""\n\t</ModelStructure>\n</fmiModelDescription>""")

    def sync_with_model_description(self):
        from pathlib import Path
        # with open(Path(__file__).parent / 'model_description.json', 'r') as f:
        import xml.etree.ElementTree as ET

        # Parse the XML file
        tree = ET.parse(Path(__file__).parent.parent / 'modelDescription - Robotti.xml')
        root = tree.getroot()

        scalar_variables = root.findall('.//ScalarVariable')
        print(scalar_variables)

        def parse_start_value(node:ET.Element):
            v= node.find('./')
            if 'start' in v.attrib:
                if v.tag=="Real":
                    return float(v.attrib['start'])
                elif v.tag=="Integer":
                    return int(v.attrib['start'])
                elif v.tag=="Boolean":
                    return bool(int(v.attrib['start']))
                elif v.tag=="String":
                    return str(v.attrib['start'])
            return None

        md_ports = {
            (int(sv.attrib['valueReference']), sv.attrib['name'],
             Fmi2Port(start_value=parse_start_value(sv), causality=Fmi2Causality.from_string(sv.attrib['causality'] if 'causality' in sv.attrib else Fmi2Causality.INPUT), initial=Fmi2Initial.from_string(sv.attrib['initial']) if 'initial' in sv.attrib else Fmi2Initial.CALCULATED,
                      variability=Fmi2Variability.from_string(sv.attrib['variability'] if 'variability' in sv.attrib else Fmi2Variability.FIXED))

             )

            for sv in scalar_variables
        }
        for p in md_ports:
            print(p)

        self.write_model_description(md_ports)

        for p in md_ports:
            print(f'\t\t\t\t self.{p[1]} = Fmi2Port( {p[2].value}, {p[2].causality}, {p[2].initial}, {p[2].variability} )')
            #start_value=None, causality: Fmi2Causality = Fmi2Causality.INPUT,
                 # initial: Fmi2Initial = Fmi2Initial.CALCULATED,
                 # variability: Fmi2Variability = Fmi2Variability.DISCRETE

        self.write_model_description([ (idx,k,getattr(self, k)) for idx, k in enumerate(self.__dict__.keys()) if isinstance(getattr(self, k), Fmi2Port)],'new_md.xml')





class Model:
    def __init__(self, state: ModelState) -> None:
        self.state = state

    # ================= FMI2 =================

    @abstractmethod
    def fmi2DoStep(
            self, current_time, step_size, no_set_fmu_state_prior_to_current_point
    ) -> Fmi2Status:
        pass

    def fmi2SetDebugLogging(self, categories, logging_on):
        return Fmi2Status.ok

    def fmi2EnterInitializationMode(self):
        return Fmi2Status.ok

    def fmi2ExitInitializationMode(self):
        self._update_outputs()
        return Fmi2Status.ok

    def fmi2SetupExperiment(self, start_time, stop_time, tolerance):
        return Fmi2Status.ok

    def fmi2Terminate(self):
        return Fmi2Status.ok

    def fmi2Reset(self):
        return Fmi2Status.ok

    def fmi2SerializeFmuState(self):
        pass
        return Fmi2Status.ok, bytes

    def fmi2DeserializeFmuState(self, bytes):
        pass

        return Fmi2Status.ok

    def fmi2GetReal(self, references):
        return self._get_value(references)

    def fmi2GetInteger(self, references):
        return self._get_value(references)

    def fmi2GetBoolean(self, references):
        return self._get_value(references)

    def fmi2GetString(self, references):
        return self._get_value(references)

    def fmi2SetReal(self, references, values):
        return self._set_value(references, values)

    def fmi2SetInteger(self, references, values):
        return self._set_value(references, values)

    def fmi2SetBoolean(self, references, values):
        return self._set_value(references, values)

    def fmi2SetString(self, references, values):
        return self._set_value(references, values)

    # ================= Helpers =================

    def _set_value(self, references, values):

        for r, v in zip(references, values):
            self.state.set_value(r, v)
#            setattr(self, self.state.value_reference_to_port[r], v)

        return Fmi2Status.ok

    def _get_value(self, references):
        values = []
        for r in references:
            values.append(self.state.get_value(r))
            # values.append(getattr(self, self.reference_to_attribute[r]))

        return Fmi2Status.ok, values


def serve(model: Model, logger):
    if logger is None:
        logger = logging.getLogger(__file__)
    # initializing message queue
    context = zmq.Context()
    socket = context.socket(zmq.REQ)

    dispatcher_endpoint = os.environ["UNIFMU_DISPATCHER_ENDPOINT"]
    logger.info(f"dispatcher endpoint received: {dispatcher_endpoint}")

    socket.connect(dispatcher_endpoint)

    # send handshake
    state = Fmi2EmptyReturn().SerializeToString()
    socket.send(state)

    # dispatch commands to model
    command = Fmi2Command()
    while True:

        msg = socket.recv()
        command.ParseFromString(msg)

        group = command.WhichOneof("command")
        data = getattr(command, command.WhichOneof("command"))

        # ================= FMI2 =================

        if group == "Fmi2Instantiate":
            result = Fmi2EmptyReturn()
        elif group == "Fmi2DoStep":
            result = Fmi2StatusReturn()
            result.status = model.fmi2DoStep(
                data.current_time, data.step_size, data.no_set_fmu_state_prior_to_current_point
            )
        elif group == "Fmi2SetDebugLogging":
            result = Fmi2StatusReturn()
            result.status = model.fmi2SetDebugLogging(data.categories, data.logging_on)
        elif group == "Fmi2SetupExperiment":
            result = Fmi2StatusReturn()
            result.status = model.fmi2SetupExperiment(
                data.start_time, data.stop_time, data.tolerance
            )
        elif group == "Fmi2EnterInitializationMode":
            result = Fmi2StatusReturn()
            result.status = model.fmi2EnterInitializationMode()
        elif group == "Fmi2ExitInitializationMode":
            result = Fmi2StatusReturn()
            result.status = model.fmi2ExitInitializationMode()
        elif group == "Fmi2FreeInstance":
            result = Fmi2FreeInstanceReturn()
            logger.info(f"Fmi2FreeInstance received, shutting down")
            sys.exit(0)
        elif group == "Fmi2Terminate":
            result = Fmi2StatusReturn()
            result.status = model.fmi2Terminate()
        elif group == "Fmi2Reset":
            result = Fmi2StatusReturn()
            result.status = model.fmi2Reset()
        elif group == "Fmi2SerializeFmuState":
            result = Fmi2SerializeFmuStateReturn()
            (result.status, result.state) = model.fmi2SerializeFmuState()
        elif group == "Fmi2DeserializeFmuState":
            result = Fmi2StatusReturn()
            result.status = model.fmi2DeserializeFmuState(data.state)
        elif group == "Fmi2GetReal":
            result = Fmi2GetRealReturn()
            result.status, result.values[:] = model.fmi2GetReal(data.references)
        elif group == "Fmi2GetInteger":
            result = Fmi2GetIntegerReturn()
            result.status, result.values[:] = model.fmi2GetInteger(data.references)
        elif group == "Fmi2GetBoolean":
            result = Fmi2GetBooleanReturn()
            result.status, result.values[:] = model.fmi2GetBoolean(data.references)
        elif group == "Fmi2GetString":
            result = Fmi2GetStringReturn()
            result.status, result.values[:] = model.fmi2GetString(data.references)
        elif group == "Fmi2SetReal":
            result = Fmi2StatusReturn()
            result.status = model.fmi2SetReal(data.references, data.values)
        elif group == "Fmi2SetInteger":
            result = Fmi2StatusReturn()
            result.status = model.fmi2SetInteger(data.references, data.values)
        elif group == "Fmi2SetBoolean":
            result = Fmi2StatusReturn()
            result.status = model.fmi2SetBoolean(data.references, data.values)
        elif group == "Fmi2SetString":
            result = Fmi2StatusReturn()
            result.status = model.fmi2SetString(data.references, data.values)
        else:
            logger.error(f"unrecognized command '{group}' received, shutting down")
            sys.exit(-1)

        state = result.SerializeToString()
        socket.send(state)
