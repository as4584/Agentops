#!/bin/bash
set -e
V=/root/studio/testing/Agentop/output/videos
SCRIPT="Want to build like a pro in Minecraft? Start by crafting the right tools, then mine deep into the earth's crust."

echo "Generating audio..."
espeak-ng -v en-us -s 145 -p 45 -a 180 -w "$V/mc_ai_audio.wav" "$SCRIPT" && echo "audio ok"

echo "Building concat list..."
printf "file '$V/mc_clip_1.mp4'\nfile '$V/mc_clip_2.mp4'\nfile '$V/mc_clip_1.mp4'\n" > /tmp/mc_concat.txt

echo "Stitching clips..."
ffmpeg -y -f concat -safe 0 -i /tmp/mc_concat.txt \
  -c:v libx264 -preset fast -crf 22 -pix_fmt yuv420p \
  "$V/mc_stitched.mp4" 2>&1 | tail -2 && echo "stitch ok"

echo "Composing final video..."
ffmpeg -y -i "$V/mc_stitched.mp4" -i "$V/mc_ai_audio.wav" \
  -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,drawtext=text='HOW TO BECOME A':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=120:box=1:boxcolor=black@0.65:boxborderw=10,drawtext=text='MINECRAFT PRO':fontcolor=0x55FF55:fontsize=72:x=(w-text_w)/2:y=185:box=1:boxcolor=black@0.7:boxborderw=10,drawtext=text='AI Generated Video':fontcolor=0xAAAAAA:fontsize=30:x=(w-text_w)/2:y=1830" \
  -c:v libx264 -preset fast -crf 20 \
  -c:a aac -b:a 128k \
  -pix_fmt yuv420p -shortest \
  "$V/minecraft_ai_pro_tips.mp4" 2>&1 | tail -2

echo ""
ls -lh "$V/minecraft_ai_pro_tips.mp4" && echo "DONE!"
