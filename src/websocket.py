# Python Imports
import json
import logging
from enum import Enum
from datetime import timedelta

# WebSokcet Import
import websockets

# FastAPI Imports
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Uvicorn Import
import uvicorn

# Redis Import
from redis import asyncio as aioredis

redis = aioredis.from_url("redis://localhost:6379", decode_responses=True)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


class ConnectionType(Enum):
    SERVER = 0
    ROBOT = 1
    ERROR = 9


app = FastAPI()

# have to change the origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# NOTE - we can also use redis to save rather than using the dict.
connected_robots = {}  # List of all Connected Robots
connected_user = {}  # List of all Connected User
user_to_robot = {}  # User to Robot Connection

# Redis Keys
h_key = "HT:"  # HOST TOKEN
c_key = "CT:"  # CLIENT TOKEN

# TOKEN KEY EXPIRATION IN REDIS
ACCESS_TOKEN_EXPIRE_MINUTES = 15
access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)


@app.post("/client_token")
async def send_client_token(machine_id: str, client_token: str):
    # User sending the client token back to server
    try:
        get_c_key = c_key + machine_id
        await redis.set(get_c_key, client_token, ex=access_token_expires)
        return "Done"
    except Exception as e:
        logger.error(f"Exception in client token - {str(e)}")


@app.get("/host_token")
async def get_host_token(machine_id: str, user_id: str = None):
    # User asking to connect the robot and if robot exist, server will return the Host Token of that robot
    try:
        # Safety check - whether that machine is already connected with the user or not,
        # As we want only 1 - 1 connection for each robot to a single user.
        if machine_id in user_to_robot:
            if (
                user_to_robot[machine_id] == user_id
            ):  # if same user want to connect the same robot again (cases like - restart connection or connection got interrupted)
                del user_to_robot[machine_id]
                logger.info(f"{user_id} already connected to -> {machine_id}")
                return {"error": f"{user_id} already connected to -> {machine_id}"}
            elif user_id in user_to_robot.values():
                logger.error(
                    f"{user_id} is already connected with another robot")
                return {"error": f"{user_id} is already connected with another robot"}
            else:
                logger.error("Remote Connection is already in use...!!!")
                return {"error": "Remote Connection is already in use...!!!"}

        # Check whether that machine is available or not
        elif machine_id in connected_robots:
            # Set this so we can keep a track of which user wants to connect which robot - this will reset / delete as soon as the robot websocket connection breaks.
            # Expecting the User ID in the Request
            logger.info(f"{user_id} wants to connect -> {machine_id}")
            return await from_client(machine_id=machine_id, user_id=user_id)

        else:
            logger.error(f"{machine_id} is Offline")
            return {"status": f"{machine_id} is Offline"}
    except Exception as e:
        logger.error(f"Exception in host token - {str(e)}")


async def from_client(*, machine_id: str, user_id: str):
    try:
        user_to_robot[machine_id] = user_id
        get_h_key = h_key + machine_id
        host_token = await redis.get(get_h_key)
        await redis.delete(get_h_key)
        return {"host_token": host_token}
    except Exception as e:
        logger.error(
            f"Exception while connecting the client : {user_id} -> host : {machine_id}"
        )


# websocket function
async def to_robot(websocket: WebSocket, from_robot: dict):
    try:
        # Add the connected robot to the dict
        if "machine_id" in from_robot:
            if not from_robot["machine_id"] in connected_robots:
                connected_robots[from_robot["machine_id"]] = websocket
                logger.info(f"Robot Connected - {from_robot['machine_id']}")
                await sent_message(
                    websocket=websocket,
                    message={
                        "message": "Successfully Connected with the Robot!!"},
                )
        msg_from_robot = await receive_message(websocket=websocket)
        if msg_from_robot:
            logger.info(
                f"Host Token received from the Robot - {from_robot['machine_id']}")
            set_h_key = h_key + msg_from_robot["machine_id"]
            await redis.set(
                set_h_key, msg_from_robot["host_token"], ex=access_token_expires
            )
            # Sent Client token back to the Robot
            get_c_key = c_key + msg_from_robot["machine_id"]
            while True:
                # we have two option either use the user to check which robot was the user connected to so we can check the right websocket connection to sent back the client token or if we use thread every single time a new connection happens it starts a new thread. have to play with it a little more.
                get_client_token = await redis.get(get_c_key)
                if get_client_token is not None:
                    await sent_message(
                        websocket=websocket,
                        message={"client_token": get_client_token},
                    )
                    logger.info(
                        f"Sent Client Token back to Robot - {from_robot['machine_id']}"
                    )
                    await redis.delete(get_c_key)
                    break
    except Exception as e:
        logger.error(f"Exception while connecting to robot - {str(e)}")


async def sent_message(websocket: WebSocket, message: str):
    try:
        message = json.dumps(message)
        await websocket.send_text(message)
    except Exception as e:
        logger.error(f"Exception while sending the message - {str(e)}")


async def receive_message(websocket: WebSocket):
    try:
        msg = await websocket.receive_text()
        json_msg = json.loads(msg)
        return json_msg
    except Exception as e:
        logger.error(f"Exception while receiving the message - {str(e)}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    message = None  # Initialize the message variable
    try:
        await websocket.accept()
        while True:
            message = await websocket.receive_text()
            json_message = json.loads(message)
            if json_message["connection_type"] == ConnectionType.ROBOT.value:
                await to_robot(websocket=websocket, from_robot=json_message)
            else:
                return "Bad Connection"

    except WebSocketDisconnect as e:
        # 1000 - safe closing
        logger.warn(f"WebSocket connection closed from the Client: {str(e)}")

    except websockets.ConnectionClosedError as e:
        logger.error("Closed Connection")

    except Exception as e:
        logger.error(f"Exception - {str(e)}")

    finally:
        # In both we have to delete data from the user_to_robots as this is a 1 - 1 Mapping.
        # When the Robot Disconnects:
        if (
            json_message["connection_type"]
            == ConnectionType.ROBOT.value
            # and json_message["machine_id"] in to_robot
        ):
            del connected_robots[json_message["machine_id"]]
            logger.info(
                f"removed the machine id from the connected robot dict - {json_message['machine_id']}"
            )
            if (
                json_message["machine_id"] in user_to_robot
            ):  # To check whether robot have any active connection or not.
                logger.info(
                    f"removed the machine to user mapped data from the user_to_robot dict -- {user_to_robot[json_message['machine_id']]}"
                )
                del user_to_robot[json_message["machine_id"]]


if __name__ == "__main__":
    uvicorn.run("websocket:app", host="0.0.0.0", port=2323, reload=True)
