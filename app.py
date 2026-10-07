import os
import re
import json
import base64
import subprocess
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# SETTINGS & PATHS
# ==========================================
OUT = Path("output")
OUT.mkdir(exist_ok=True)

TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini")
IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "dall-e-3")
TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1")

TOPIC = os.getenv("VIDEO_TOPIC", "Daily Motivation and Success Tips")
LANGUAGE = os.getenv("VIDEO_LANGUAGE", "English")
SCENES = int(os.getenv("VIDEO_SCENES", "3"))

PRIVACY = os.getenv("VIDEO_PRIVACY", "private")
CATEGORY = os.getenv("YOUTUBE_CATEGORY_ID", "24")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==========================================
# 1. GENERATE SCRIPT & PROMPTS
# ==========================================
def generate_script(topic, language, scenes_count):
    prompt = f"""
    Create a short video script about '{topic}' in {language}.
    Break it down into exactly {scenes_count} short visual scenes.
    For each scene, provide:
    1. 'narration': The spoken voiceover text.
    2. 'image_prompt': A clear prompt to generate a background image for this scene.
    3. 'title': A catchy video title.
    4. 'description': Video description.

    Return ONLY a valid JSON object matching this structure:
    {{
      "title": "...",
      "description": "...",
      "scenes": [
        {{"narration": "...", "image_prompt": "..."}}
      ]
    }}
    """
    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# ==========================================
# 2. GENERATE AUDIO (TTS)
# ==========================================
def generate_audio(text, output_file):
    response = client.audio.speech.create(
        model=TTS_MODEL,
        voice="alloy",
        input=text
    )
    response.stream_to_file(output_file)

# ==========================================
# 3. GENERATE IMAGE
# ==========================================
def generate_image(prompt, output_file):
    response = client.images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        n=1,
        size="1024x1024"
    )
    import requests
    img_url = response.data[0].url
    img_data = requests.get(img_url).content
    with open(output_file, 'wb') as handler:
        handler.write(img_data)

# ==========================================
# 4. BUILD VIDEO (FFMPEG)
# ==========================================
def build_scene_video(image_path, audio_path, output_path):
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest", str(output_path)
    ]
    subprocess.run(cmd, check=True)

def concatenate_videos(video_list, output_path):
    concat_file = OUT / "concat.txt"
    with open(concat_file, "w") as f:
        for v in video_list:
            f.write(f"file '{v.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy", str(output_path)
    ]
    subprocess.run(cmd, check=True)

# ==========================================
# 5. YOUTUBE UPLOAD
# ==========================================
def upload_to_youtube(video_path, title, description):
    creds_json = os.getenv("YOUTUBE_CREDENTIALS")
    if not creds_json:
        print("Skipping YouTube upload: YOUTUBE_CREDENTIALS secret not found.")
        return

    creds_data = json.loads(creds_json)
    creds = Credentials.from_authorized_user_info(creds_data)
    youtube = build("youtube", "v3", credentials=creds)

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

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")

    print(f"Video uploaded successfully! Video ID: {response.get('id')}")

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    print("
