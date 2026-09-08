#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const projectRequire = createRequire(path.join(process.cwd(), 'package.json'));
const bridgeRequire = createRequire(import.meta.url);

function textValue(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value.text === 'string') return value.text;
  if (typeof value.toString === 'function') return value.toString();
  return String(value);
}

function resolveLibraryEntry() {
  const resolvers = [projectRequire, bridgeRequire];
  let lastError;
  for (const resolver of resolvers) {
    try {
      return resolver.resolve('youtubei.js');
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

function findPackageInfo(entryPath) {
  let directory = path.dirname(entryPath);
  while (true) {
    const candidate = path.join(directory, 'package.json');
    if (fs.existsSync(candidate)) {
      const payload = JSON.parse(fs.readFileSync(candidate, 'utf8'));
      if (payload?.name === 'youtubei.js') return { path: candidate, payload };
    }
    const parent = path.dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }
  return { path: null, payload: {} };
}

async function loadLibrary() {
  const modulePath = resolveLibraryEntry();
  const module = await import(pathToFileURL(modulePath).href);
  const packageInfo = findPackageInfo(modulePath);
  return {
    ...module,
    version: packageInfo.payload.version || 'unknown',
    modulePath,
  };
}

async function resolveChannelId(yt, url) {
  const endpoint = await yt.resolveURL(url);
  const payload = endpoint?.payload || {};
  const channelId = payload.browseId || payload.browse_id;
  if (!channelId) {
    throw new Error(`resolved URL did not expose a channel browse ID: ${url}`);
  }
  return channelId;
}

async function enumerateChannelVideos(url) {
  const { Innertube } = await loadLibrary();
  const yt = await Innertube.create({ generate_session_locally: true });
  const channelId = await resolveChannelId(yt, url);
  const channel = await yt.getChannel(channelId);
  let feed = await channel.getVideos();
  let emitted = 0;

  while (true) {
    // feed.videos is a YouTube.js ObservedArray, not necessarily a native Array.
    // Array.from() deliberately consumes any iterable/array-like parser collection.
    const videos = feed?.videos ? Array.from(feed.videos) : [];
    for (const video of videos) {
      const id = video?.id || video?.content_id || video?.contentId || '';
      if (!id) continue;

      let title = textValue(video.title);
      let publishedText = textValue(video.published);
      let viewCountText = textValue(video.view_count);
      let durationText = textValue(video.duration);

      // Newer YouTube layouts may expose videos as LockupView nodes. Their
      // human-readable metadata is nested in metadata.metadata_rows.
      if (video?.metadata) {
        if (!title) title = textValue(video.metadata.title);
        const rows = video.metadata.metadata?.metadata_rows || [];
        const parts = [];
        for (const row of rows) {
          for (const part of row?.metadata_parts || []) {
            const value = textValue(part?.text).trim();
            if (value) parts.push(value);
          }
        }
        if (!publishedText) {
          publishedText = parts.find((value) => /(?:ago|today|yesterday)$/i.test(value)) || '';
        }
        if (!viewCountText) {
          viewCountText = parts.find((value) => /views?$/i.test(value)) || '';
        }
      }

      process.stdout.write(JSON.stringify({
        id,
        title,
        published_text: publishedText,
        duration_text: durationText,
        view_count_text: viewCountText,
      }) + '\n');
      emitted += 1;
    }

    if (!feed?.has_continuation) break;
    feed = await feed.getContinuation();
  }

  if (emitted === 0 && channel?.has_videos) {
    throw new Error('YouTube.js returned a videos tab but no video entries could be parsed');
  }
}

async function main() {
  const [mode, value] = process.argv.slice(2);
  if (mode === '--check') {
    const library = await loadLibrary();
    process.stdout.write(JSON.stringify({
      available: true,
      version: library.version,
      module_path: library.modulePath,
    }) + '\n');
    return;
  }
  if (mode === '--enumerate-channel-videos') {
    if (!value) throw new Error('channel URL is required');
    await enumerateChannelVideos(value);
    return;
  }
  throw new Error('expected --check or --enumerate-channel-videos <url>');
}

main().catch((error) => {
  const message = error?.stack || error?.message || String(error);
  process.stderr.write(`[yt-discover:youtubejs] ${message}\n`);
  process.exitCode = 1;
});
