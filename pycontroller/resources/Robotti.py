
from backend import Model, ModelState, Fmi2Status, Fmi2Port


class RobottiState(ModelState):

    def __init__(self):
        super().__init__()
        self.port_a = Fmi2Port(False)

        self.build()


class RobottiModel(Model):
    def fmi2DoStep(self, current_time, step_size, no_set_fmu_state_prior_to_current_point) -> Fmi2Status:
        self.state.port_a.value=0
        return Fmi2Status.ok

    def __init__(self, state: RobottiState) -> None:
        super().__init__(state)
        self.state = state



if __name__ == "__main__":
    RobottiState().sync_with_model_description()