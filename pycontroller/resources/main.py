from Robotti import RobottiModel, RobottiState
from backend import serve
import logging


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__file__)


if __name__ == "__main__":

    serve( RobottiModel(RobottiState()),logger)