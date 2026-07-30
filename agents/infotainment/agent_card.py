from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from prompts import build_orchestrator_description


PLAY_MUSIC = AgentSkill(
    id="play_music",
    name="Play music",
    description="Play a song; returns path to audio file.",
    tags=["music", "song", "play", "audio"],
    examples=["play music", "play a song", "play Morning Drive"],
)

PLAY_INFOTAINMENT = AgentSkill(
    id="play_infotainment",
    name="Play Infotainment",
    description="Play various entertainment options such as audiobooks, podcasts, videos, meditation, and movies.",
    tags=["infotainment", "audiobook", "podcast", "video", "meditation", "movie"],
    examples=[
        "play me an audiobook",
        "start a podcast",
        "show me a funny video",
        "play some meditation music",
        "play movie trailers"
    ],
)

def build_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="Infotainment",
        description=build_orchestrator_description(),
        url=base_url.rstrip("/") + "/",
        version="1.0.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(),
        skills=[PLAY_MUSIC, PLAY_INFOTAINMENT],
    )
