
import os
import json
import time
import asyncio
import requests
from pathlib import Path
import subprocess

import edge_tts
from google import genai
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# SETTINGS & PATHS
# ==========================================
OUT = Path("output")
OUT.mkdir(exist_ok=True)

TOPIC = os.getenv("VIDEO_TOPIC", "Daily Motivation and Success Tips")
LANGUAGE = os.getenv("VIDEO_LANGUAGE", "English")

raw_scenes = os.getenv("VIDEO_SCENES", "").strip()
SCENES = int(raw_scenes) if raw_scenes.isdigit() else 3

PRIVACY = os.getenv("VIDEO_PRIVACY", "private")
CATEGORY = os.getenv("YOUTUBE_CATEGORY_ID", "24")

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None


# ==========================================
# 1. SCRIPT GENERATION
# ==========================================
def generate_script(topic, language, scenes_count):
    if not gemini_client:
        print("GEMINI_API_KEY missing; using fallback template.")
        return {
            "title": f"Motivation: {topic}",
            "description": f"Inspiring video about {topic}",
            "scenes": [
                {
                    "narration": "Believe in yourself and take action today.",
                    "image_prompt": "cinematic motivational scene, highly detailed"
                },
                {
                    "narration": "Success requires consistency and hard work.",
                    "image_prompt": "person standing on a mountain at sunset"
                },
                {
                    "narration": "Never give up on your dreams.",
                    "image_prompt": "bright golden path toward a hopeful future"
                }
            ]
        }

    prompt = f"""
Create a short video script about '{topic}' in {language}.
Create exactly {scenes_count} scenes.
Return ONLY valid JSON with keys: title, description, scenes.
Each scene must contain narration and image_prompt.
"""

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    raw_text = (response.text or "").strip()
    raw_text = raw_text.replace("```json", "").replace("```", "").strip()
    return json.loads(raw_text)


# ==========================================
# 2. AUDIO GENERATION
# ==========================================
async def generate_audio_async(text, output_file):
    voice = os.getenv("TTS_VOICE", "en-US-ChristopherNeural")
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_file))


def generate_audio(text, output_file):
    asyncio.run(generate_audio_async(text, output_file))


# ==========================================
# 3. IMAGE GENERATION
# ==========================================
def generate_image(prompt, output_file):
    formatted_prompt = requests.utils.quote(prompt)
    image_url = (
        f"https://image.pollinations.ai/prompt/{formatted_prompt}"
        "?width=1080&height=1920&nologo=true"
    )

    for attempt in range(1, 4):
        try:
            response = requests.get(image_url, timeout=60)

            if response.status_code == 200 and len(response.content) > 1000:
                with open(output_file, "wb") as f:
                    f.write(response.content)
                return

            print(f"Image attempt {attempt}: HTTP {response.status_code}")

        except Exception as exc:
            print(f"Image attempt {attempt} failed: {exc}")

        time.sleep(3)

    raise RuntimeError("Image generation failed after 3 attempts.")


# ==========================================
# 4. BUILD VIDEO
# ==========================================
def build_scene_video(image_path, audio_path, output_path):
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(output_path)
    ]

    subprocess.run(cmd, check=True)


def concatenate_videos(video_list, output_path):
    concat_file = OUT / "concat.txt"

    with open(concat_file, "w", encoding="utf-8") as f:
        for video in video_list:
            f.write(f"file '{video.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(output_path)
    ]

    subprocess.run(cmd, check=True)


# ==========================================
# 5. YOUTUBE UPLOAD
# ==========================================
def upload_to_youtube(video_path, title, description):
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")

    missing = [
        name
        for name, value in [
            ("YOUTUBE_CLIENT_ID", client_id),
            ("YOUTUBE_CLIENT_SECRET", client_secret),
            ("YOUTUBE_REFRESH_TOKEN", refresh_token)
        ]
        if not value
    ]

    if missing:
        raise RuntimeError(
            "YouTube upload cannot start. Missing environment variables: "
            + ", ".join(missing)
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )

    creds.refresh(Request())

    youtube = build(
        "youtube",
        "v3",
        credentials=creds,
        cache_discovery=False
    )

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": CATEGORY
        },
        "status": {
            "privacyStatus": PRIVACY
        }
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=8 * 1024 * 1024,
        resumable=True
    )

    upload_request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None

    while response is None:
        status, response = upload_request.next_chunk()

        if status:
            print(
                f"YouTube upload progress: "
                f"{int(status.progress() * 100)}%"
            )

    video_id = response.get("id")

    if not video_id:
        raise RuntimeError("YouTube did not return a video ID.")

    print(f"YOUTUBE_UPLOAD_SUCCESS: {video_id}")
    print(f"Video URL: https://www.youtube.com/watch?v={video_id}")


# ==========================================
# 6. MAIN EXECUTION
# ==========================================
def main():
    print("--- Starting AI Video Generator ---")

    print("Generating script...")
    data = generate_script(TOPIC, LANGUAGE, SCENES)
    print(f"Title: {data['title']}")

    scene_videos = []

    for idx, scene in enumerate(data["scenes"]):
        print(f"Processing scene {idx + 1}/{len(data['scenes'])}...")

        audio_file = OUT / f"scene_{idx + 1}.mp3"
        image_file = OUT / f"scene_{idx + 1}.jpg"
        video_file = OUT / f"scene_{idx + 1}.mp4"

        print("Generating speech...")
        generate_audio(scene["narration"], audio_file)

        print("Generating image...")
        generate_image(scene["image_prompt"], image_file)

        print("Rendering scene video...")
        build_scene_video(image_file, audio_file, video_file)
        scene_videos.append(video_file)

    if not scene_videos:
        raise RuntimeError("No scenes generated; cannot create video.")

    final_video = OUT / "final_video.mp4"

    print("Merging all scene videos...")
    concatenate_videos(scene_videos, final_video)
    print(f"Final video ready: {final_video}")

    print("Starting YouTube upload...")
    upload_to_youtube(final_video, data["title"], data["description"])

    print("--- Video generated and YouTube upload confirmed. ---")


if __name__ == "__main__":
    main()
