# -*- coding: utf-8 -*-
import logging
import json
import uuid
import time
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone

import ask_sdk_core.utils as ask_utils
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractExceptionHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── AWS clients ───────────────────────────────────────────────────────────────
iot_client  = boto3.client("iot-data")
dynamodb    = boto3.resource("dynamodb")

devices_table  = dynamodb.Table("petdoor_devices")
pets_table     = dynamodb.Table("petdoor_pets")
commands_table = dynamodb.Table("petdoor_commands")

# ── Session-level thing name (reset per Lambda container, fine for Alexa) ─────
THING_NAME: str | None = None


# ══════════════════════════════════════════════════════════════════════════════
#  DynamoDB helpers
# ══════════════════════════════════════════════════════════════════════════════

def get_alexa_user_id(handler_input) -> str:
    return handler_input.request_envelope.session.user.user_id


def get_thing_name_by_location(user_id: str, location_name: str) -> str | None:
    """
    Returns the thing_name of the first enabled device whose
    location_name matches (case-insensitive) for the given user.
    """
    try:
        response = devices_table.query(
            KeyConditionExpression=Key("user_id").eq(user_id)
        )
        for device in response.get("Items", []):
            if (
                device.get("location_name", "").lower() == location_name.lower()
                and device.get("enabled", True)
            ):
                return device.get("thing_name")
        return None
    except Exception as e:
        logger.error("get_thing_name_by_location error: %s", e)
        return None


def get_default_thing_name(user_id: str) -> str | None:
    return get_thing_name_by_location(user_id, "default")


def initialize_default_thing(handler_input) -> str | None:
    """Load the default device into THING_NAME if not already set."""
    global THING_NAME
    if THING_NAME:
        return THING_NAME
    user_id   = get_alexa_user_id(handler_input)
    thing     = get_default_thing_name(user_id)
    if thing:
        THING_NAME = thing
    return THING_NAME


def require_thing(handler_input):
    """
    Returns (thing_name, error_response).
    If no device is connected, error_response is a ready Response object.
    """
    thing = THING_NAME or initialize_default_thing(handler_input)
    if not thing:
        speak = (
            "No hay ninguna puerta conectada. "
            "Di 'conectar con la puerta de' seguido del nombre de la ubicación."
        )
        resp = (
            handler_input.response_builder
                .speak(speak)
                .ask(speak)
                .response
        )
        return None, resp
    return thing, None


# ── Command helpers ───────────────────────────────────────────────────────────

def new_command_id() -> str:
    return f"cmd-{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_command(thing_name: str, action: str, status: str = "sent",
                   command_id: str = None, error: str = "") -> str:
    """Write a row to petdoor_commands and return the command_id."""
    cmd_id = command_id or new_command_id()
    try:
        commands_table.put_item(Item={
            "thing_name":        thing_name,
            "command_timestamp": now_iso(),
            "command_id":        cmd_id,
            "action":            action,
            "status":            status,
            "error":             error,
        })
    except Exception as e:
        logger.error("record_command error: %s", e)
    return cmd_id


def update_command_status(thing_name: str, command_timestamp: str,
                          status: str, error: str = ""):
    """Update status on an existing command row (requires the SK)."""
    try:
        commands_table.update_item(
            Key={"thing_name": thing_name, "command_timestamp": command_timestamp},
            UpdateExpression="SET #s = :s, #e = :e",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":s": status, ":e": error},
        )
    except Exception as e:
        logger.error("update_command_status error: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
#  Shadow helpers  (new shadow shape)
# ══════════════════════════════════════════════════════════════════════════════

def get_shadow(thing_name: str = None) -> dict:
    try:
        resp = iot_client.get_thing_shadow(thingName=thing_name or THING_NAME)
        return json.loads(resp["payload"].read())
    except ClientError as e:
        logger.error("get_shadow error: %s", e)
        return {}


def update_desired(patch: dict, thing_name: str = None) -> bool:
    payload = json.dumps({"state": {"desired": patch}})
    try:
        iot_client.update_thing_shadow(
            thingName=thing_name or THING_NAME,
            payload=payload.encode()
        )
        return True
    except ClientError as e:
        logger.error("update_desired error: %s", e)
        return False


def get_reported(thing_name: str = None) -> dict:
    return get_shadow(thing_name).get("state", {}).get("reported", {})


def get_desired_state(thing_name: str = None) -> dict:
    return get_shadow(thing_name).get("state", {}).get("desired", {})


# ── Convenience accessors for the new shadow shape ────────────────────────────

def reported_door(thing_name: str = None) -> dict:
    """reported.door  →  {state, motor_state, last_opened_at, last_command_id}"""
    return get_reported(thing_name).get("door", {})


def reported_config(thing_name: str = None) -> dict:
    """reported.config  →  {mode, open_duration_sec, cooldown_sec, register_duration_sec}"""
    return get_reported(thing_name).get("config", {})


def reported_last_event(thing_name: str = None) -> dict:
    """reported.last_event  →  {reader, tag, detected_at}"""
    return get_reported(thing_name).get("last_event", {})


# ══════════════════════════════════════════════════════════════════════════════
#  Pets (DynamoDB petdoor_pets) helpers
# ══════════════════════════════════════════════════════════════════════════════

def get_pets(thing_name: str) -> list[dict]:
    try:
        resp = pets_table.query(
            KeyConditionExpression=Key("thing_name").eq(thing_name)
        )
        return resp.get("Items", [])
    except Exception as e:
        logger.error("get_pets error: %s", e)
        return []


def find_pet_by_tag(thing_name: str, rfid_tag: str) -> dict | None:
    pets = get_pets(thing_name)
    for p in pets:
        if p.get("rfid_tag") == rfid_tag:
            return p
    return None


def find_pet_by_name(thing_name: str, name: str) -> dict | None:
    pets = get_pets(thing_name)
    name_lower = name.lower()
    for p in pets:
        if p.get("name", "").lower() == name_lower:
            return p
    return None


def register_pet_in_db(thing_name: str, rfid_tag: str, pet_name: str) -> bool:
    try:
        pets_table.put_item(Item={
            "thing_name":   thing_name,
            "rfid_tag":     rfid_tag,
            "name":         pet_name,
            "enabled":      True,
            "created_at":   now_iso(),
            "last_seen_at": "",
        })
        return True
    except Exception as e:
        logger.error("register_pet_in_db error: %s", e)
        return False


def delete_pet_from_db(thing_name: str, rfid_tag: str) -> bool:
    try:
        pets_table.delete_item(
            Key={"thing_name": thing_name, "rfid_tag": rfid_tag}
        )
        return True
    except Exception as e:
        logger.error("delete_pet_from_db error: %s", e)
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Skill handlers
# ══════════════════════════════════════════════════════════════════════════════

class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        initialize_default_thing(handler_input)
        if THING_NAME:
            door   = reported_door().get("state", "desconocido")
            mode   = reported_config().get("mode", "desconocido")
            speak  = (
                f"Bienvenido a la puerta inteligente. "
                f"La puerta está {door} y el modo es {mode}. "
                f"¿Qué deseas hacer?"
            )
        else:
            speak = (
                "Bienvenido a la puerta inteligente. "
                "No hay ninguna puerta conectada. "
                "Di 'conectar con la puerta de' seguido de la ubicación."
            )
        return (
            handler_input.response_builder
                .speak(speak)
                .ask("¿Qué deseas hacer?")
                .response
        )


# ── Device connection ─────────────────────────────────────────────────────────

class ConnectToDoorIntentHandler(AbstractRequestHandler):
    """
    ConnectToDoorIntent  —  slot: {locationName}
    Looks up a device by location_name for this Alexa user and sets THING_NAME
    for the rest of the session.
    """
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("ConnectToDoorIntent")(handler_input)

    def handle(self, handler_input):
        global THING_NAME

        slots    = handler_input.request_envelope.request.intent.slots
        loc_slot = slots.get("location") if slots else None
        location = loc_slot.value.strip() if loc_slot and loc_slot.value else None

        if not location:
            speak = "No entendí la ubicación. Di por ejemplo: conectar con entrada."
            return handler_input.response_builder.speak(speak).ask(speak).response

        user_id = get_alexa_user_id(handler_input)
        thing   = get_thing_name_by_location(user_id, location)

        if not thing:
            speak = (
                f"No encontré ninguna puerta en la ubicación {location}. "
                "Verifica el nombre e intenta de nuevo."
            )
            return handler_input.response_builder.speak(speak).ask("¿Qué deseas hacer?").response

        THING_NAME = thing
        door = reported_door(thing).get("state", "desconocido")
        speak = (
            f"Conectado a la puerta de {location}. "
            f"La puerta está {door}. "
            "¿Qué deseas hacer?"
        )
        return handler_input.response_builder.speak(speak).ask("¿Qué deseas hacer?").response


# ── Mode setters ──────────────────────────────────────────────────────────────

class SetModeAutoIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("SetModeAutoIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err
        ok    = update_desired({"config": {"mode": "auto"}})
        speak = "La puerta fue puesta en modo automático." if ok else "No pude cambiar el modo. Intenta de nuevo."
        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


class SetModeClosedIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("SetModeClosedIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err
        ok    = update_desired({"config": {"mode": "closed"}})
        speak = "La puerta fue cerrada y bloqueada." if ok else "No pude cerrar la puerta. Intenta de nuevo."
        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


class SetModeOpenIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("SetModeOpenIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err
        ok    = update_desired({"config": {"mode": "open"}})
        speak = "La puerta fue abierta." if ok else "No pude abrir la puerta. Intenta de nuevo."
        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


# ── Timers ────────────────────────────────────────────────────────────────────

class SetAutoTimerIntentHandler(AbstractRequestHandler):
    """SetAutoTimerIntent  —  slot: {openTime}  (seconds, 5-300)"""
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("SetAutoTimerIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err

        slots = handler_input.request_envelope.request.intent.slots
        raw   = (slots.get("openTime").value if slots and slots.get("openTime") else None)

        if not raw or not raw.isdigit():
            speak = "No entendí el tiempo. Di algo como: timer de apertura 30."
            return handler_input.response_builder.speak(speak).ask(speak).response

        seconds = int(raw)
        if not (5 <= seconds <= 300):
            speak = "El tiempo debe ser entre 5 y 300 segundos."
            return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response

        ok    = update_desired({"config": {"open_duration_sec": seconds}})
        speak = (
            f"Temporizador de apertura configurado a {seconds} segundos."
            if ok else
            "No pude configurar el temporizador. Intenta de nuevo."
        )
        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


class SetRegisterDurationTimerIntentHandler(AbstractRequestHandler):
    """SetRegisterDurationTimerIntent  —  slot: {registerTime}  (seconds, 5-120)"""
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("SetRegisterDurationTimerIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err

        slots = handler_input.request_envelope.request.intent.slots
        raw   = (slots.get("registerTime").value if slots and slots.get("registerTime") else None)

        if not raw or not raw.isdigit():
            speak = "No entendí el tiempo. Di algo como: tiempo de registro veinte."
            return handler_input.response_builder.speak(speak).ask(speak).response

        seconds = int(raw)
        if not (5 <= seconds <= 8):
            speak = "El tiempo de registro debe ser entre 5 y 8 segundos."
            return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response

        ok    = update_desired({"config": {"register_duration_sec": seconds}})
        speak = (
            f"Duración de registro configurada a {seconds} segundos."
            if ok else
            "No pude configurar la duración de registro. Intenta de nuevo."
        )
        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


# ── Tag / Pet management ──────────────────────────────────────────────────────

class AddNewTagIntentHandler(AbstractRequestHandler):
    """
    AddNewTagIntent  —  slot: {petName}

    Flow:
      1. Send a "register" door_command to the shadow so the device enters
         registration mode and reads an RFID tag.
      2. Poll reported.last_event.tag for up to register_duration_sec seconds
         (max 8 s here because Alexa has a ~10 s response limit).
      3. If a new tag appears that is not already in petdoor_pets, register it.
      4. Write the command + final status to petdoor_commands.
    """
    POLL_INTERVAL = 1      # seconds between shadow polls
    MAX_WAIT      = 8      # hard ceiling imposed by Alexa timeout

    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AddNewTagIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err

        slots        = handler_input.request_envelope.request.intent.slots
        pet_name_raw = (slots.get("petName").value if slots and slots.get("petName") else None)
        pet_name     = pet_name_raw.strip() if pet_name_raw else None

        if not pet_name:
            speak = "No entendí el nombre de la mascota. ¿Cómo se llama?"
            return handler_input.response_builder.speak(speak).ask(speak).response

        # ── Snapshot current last_event tag before issuing the command ────────
        time_before= reported_last_event(thing).get("detected_at", "")
        # ── Issue the register command to the shadow ───────────────────────────
        cmd_id        = new_command_id()
        cmd_timestamp = now_iso()
        patch = {
            "door_command": {
                "action":     "register",
                "request_id": cmd_id,
            }
        }
        if not update_desired(patch, thing):
            record_command(thing, "register", "failed", cmd_id,
                           error="could not update shadow")
            speak = "No pude iniciar el modo de registro. Intenta de nuevo."
            return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response

        record_command(thing, "register", "sent", cmd_id)

        # ── Poll for a new RFID tag ───────────────────────────────────────────
        new_tag      = None
        elapsed      = 0
        register_sec = reported_config(thing).get("register_duration_sec", 20)
        wait_limit   = min(register_sec, self.MAX_WAIT)

        while elapsed < wait_limit:
            time.sleep(self.POLL_INTERVAL)
            elapsed += self.POLL_INTERVAL
            event   = reported_last_event(thing)
            tag_now = event.get("tag", "")
            time_now= event.get("detected_at", "")
            if tag_now and time_now != time_before:
                new_tag = tag_now
                break

        # ── No tag detected in time ───────────────────────────────────────────
        if not new_tag:
            update_command_status(thing, cmd_timestamp, "timeout",
                                  error="no tag detected within window")
            speak = (
                "No detecté ninguna etiqueta. "
                "Acerca el tag al lector y vuelve a intentarlo."
            )
            return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response

        # ── Tag already registered? ───────────────────────────────────────────
        if find_pet_by_tag(thing, new_tag):
            update_command_status(thing, cmd_timestamp, "duplicate",
                                  error=f"tag {new_tag} already registered")
            speak = "Esa etiqueta ya pertenece a una mascota registrada."
            return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response

        # ── Register in DynamoDB ──────────────────────────────────────────────
        ok = register_pet_in_db(thing, new_tag, pet_name)
        if ok:
            update_command_status(thing, cmd_timestamp, "completed")
            speak = f"{pet_name} fue registrado correctamente con la etiqueta {new_tag}."
        else:
            update_command_status(thing, cmd_timestamp, "failed",
                                  error="DynamoDB write failed")
            speak = "Detecté la etiqueta pero no pude guardarla. Intenta de nuevo."

        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


class RemoveTagIntentHandler(AbstractRequestHandler):
    """
    RemoveTagIntent  —  slot: {petName}
 
    Removes a pet by name from petdoor_pets.
    If petName is absent, falls back to removing by the currently present tag.
    """
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("RemoveTagIntent")(handler_input)
 
    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err
 
        slots        = handler_input.request_envelope.request.intent.slots
        pet_name_raw = (slots.get("petName").value if slots and slots.get("petName") else None)
        pet_name     = pet_name_raw.strip() if pet_name_raw else None
 
        if not pet_name:
            speak = "No entendí el nombre de la mascota. Di el nombre de la mascota que deseas eliminar."
            return handler_input.response_builder.speak(speak).ask(speak).response
 
        pet = find_pet_by_name(thing, pet_name)
        if not pet:
            speak = f"No encontré ninguna mascota llamada {pet_name}."
            return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response
 
        ok    = delete_pet_from_db(thing, pet["rfid_tag"])
        speak = (
            f"{pet_name} fue eliminado correctamente."
            if ok else
            f"No pude eliminar a {pet_name}. Intenta de nuevo."
        )
        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response
 
# ── Queries ───────────────────────────────────────────────────────────────────

class GetLastTagIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetLastTagIntent")(handler_input)
 
    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err
 
        event    = reported_last_event(thing)
        last_tag = event.get("tag", "")
 
        if not last_tag:
            speak = "No hay ningún registro reciente de etiquetas."
            return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response
 
        # ── Resolve pet name ──────────────────────────────────────────────────
        pet = find_pet_by_tag(thing, last_tag)
        name = pet["name"] if pet else "una mascota no registrada"
 
        # ── Resolve reader ────────────────────────────────────────────────────
        reader_raw = event.get("reader", "")
        reader_map = {"entry": "entrada", "exit": "salida"}
        reader     = reader_map.get(reader_raw.lower(), reader_raw) if reader_raw else None
 
        # ── Resolve time ──────────────────────────────────────────────────────
        detected_at = event.get("detected_at", "")
        time_phrase = None
        if detected_at:
            try:
                dt      = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
                now     = datetime.now(timezone.utc)
                minutes = int((now - dt).total_seconds() // 60)
                if minutes < 1:
                    time_phrase = "hace menos de un minuto"
                elif minutes < 60:
                    time_phrase = f"hace {minutes} minutos"
                else:
                    time_phrase = f"hace {minutes // 60} horas"
            except ValueError:
                time_phrase = None
 
        # ── Build response ────────────────────────────────────────────────────
        speak = f"La última detección fue {name}"
        if reader:
            speak += f" por el lector de {reader}"
        if time_phrase:
            speak += f", {time_phrase}"
        speak += "."
 
        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response
 

class GetDoorStateIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetDoorStateIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err

        door = reported_door(thing)
        state = door.get("state", "desconocido")
        mode  = reported_config(thing).get("mode", "desconocido")
        speak = f"La puerta está {state} y el modo es {mode}."
        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


class GetMotorStateIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetMotorStateIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err

        motor = reported_door(thing).get("motor_state", "desconocido")
        state_map = {
            "idle":    "en reposo",
            "running": "en movimiento",
            "error":   "en estado de error",
            "stalled": "bloqueado",
        }
        speak = f"El motor está {state_map.get(motor, motor)}."
        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


class GetLastOpenTimeIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetLastOpenTimeIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err

        ts = reported_door(thing).get("last_opened_at", "")

        if not ts:
            speak = "No hay registro de cuándo se abrió la puerta por última vez."
            return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response

        try:
            dt      = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            now     = datetime.now(timezone.utc)
            minutes = int((now - dt).total_seconds() // 60)

            if minutes < 1:
                speak = "La puerta se abrió hace menos de un minuto."
            elif minutes < 60:
                speak = f"La puerta se abrió hace {minutes} minutos."
            else:
                speak = f"La puerta se abrió hace {minutes // 60} horas."
        except ValueError:
            speak = f"La última apertura fue registrada como {ts}."

        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


class GetListOfPetsIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GetListOfPetsIntent")(handler_input)

    def handle(self, handler_input):
        thing, err = require_thing(handler_input)
        if err:
            return err

        pets = get_pets(thing)
        enabled_pets = [p for p in pets if p.get("enabled", True)]

        if not enabled_pets:
            speak = "No hay mascotas registradas."
        else:
            names = ", ".join(p.get("name", "desconocido") for p in enabled_pets)
            speak = f"Las mascotas registradas son: {names}."

        return handler_input.response_builder.speak(speak).ask("¿Qué más deseas hacer?").response


# ── Built-in handlers ─────────────────────────────────────────────────────────

class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        speak = (
            "Puedes decirme: conectar con la puerta de entrada, "
            "abre la puerta, cierra la puerta, modo automático, "
            "registrar mascota llamada Luna, eliminar mascota Luna, "
            "¿cuál fue el último tag?, ¿está la puerta abierta?, "
            "¿cuándo se abrió por última vez?, listar mascotas, "
            "timer de apertura 30, tiempo de registro 20. "
            "¿Qué deseas hacer?"
        )
        return (
            handler_input.response_builder
                .speak(speak)
                .ask("¿Qué deseas hacer?")
                .response
        )


class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (
            ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) or
            ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input)
        )

    def handle(self, handler_input):
        return handler_input.response_builder.speak("Hasta luego.").response


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class IntentReflectorHandler(AbstractRequestHandler):
    """Fallback debugger — keep last in chain."""
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("IntentRequest")(handler_input)

    def handle(self, handler_input):
        intent_name = ask_utils.get_intent_name(handler_input)
        speak = f"Activaste el intent {intent_name}."
        return handler_input.response_builder.speak(speak).response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.error(exception, exc_info=True)
        speak = "Lo siento, ocurrió un error. Por favor intenta de nuevo."
        return (
            handler_input.response_builder
                .speak(speak)
                .ask(speak)
                .response
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Skill builder
# ══════════════════════════════════════════════════════════════════════════════

sb = SkillBuilder()

# Registration order matters — IntentReflectorHandler must be last
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(ConnectToDoorIntentHandler())
sb.add_request_handler(SetModeAutoIntentHandler())
sb.add_request_handler(SetModeClosedIntentHandler())
sb.add_request_handler(SetModeOpenIntentHandler())
sb.add_request_handler(SetAutoTimerIntentHandler())
sb.add_request_handler(SetRegisterDurationTimerIntentHandler())
sb.add_request_handler(AddNewTagIntentHandler())
sb.add_request_handler(RemoveTagIntentHandler())
sb.add_request_handler(GetLastTagIntentHandler())
sb.add_request_handler(GetDoorStateIntentHandler())
sb.add_request_handler(GetMotorStateIntentHandler())
sb.add_request_handler(GetLastOpenTimeIntentHandler())
sb.add_request_handler(GetListOfPetsIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_request_handler(IntentReflectorHandler())  # must be last

sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()