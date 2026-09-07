#!/usr/bin/env node

async function loadYoutubeJs() {
    try {
        return await import("youtubei.js");
    } catch (error) {
        console.error(`could not load youtubei.js: ${error.message}`);
        process.exit(1);
    }
}

if (process.argv[2] === "--probe") {
    await loadYoutubeJs();
    console.log("youtubei.js");
    process.exit(0);
}

const source = process.argv[2];
if (!source) {
    console.error("source URL is required");
    process.exit(2);
}

const { Innertube } = await loadYoutubeJs();
const youtube = await Innertube.create();

try {
    // Early integration assumes getInfo() can resolve the supplied source and
    // that the result exposes a plain videos array.
    const result = await youtube.getInfo(source);
    const videos = Array.isArray(result.videos) ? result.videos : [];

    const entries = videos.map((video) => ({
        id: video.id,
        title: video.title?.text ?? video.title,
        uploader: video.author?.name ?? video.author,
        duration: video.duration?.seconds ?? video.duration,
        upload_date: video.published?.date ?? null,
        is_live: video.is_live ?? false,
    }));

    process.stdout.write(JSON.stringify(entries));
} catch (error) {
    console.error(`YouTube.js enumeration failed: ${error.message}`);
    process.exit(1);
}
