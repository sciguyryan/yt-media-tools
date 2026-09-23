package org.sciguyryan.ytmediatools.newpipe;

import com.google.gson.Gson;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.schabi.newpipe.extractor.NewPipe;
import org.schabi.newpipe.extractor.downloader.Downloader;
import org.schabi.newpipe.extractor.downloader.Request;
import org.schabi.newpipe.extractor.downloader.Response;
import org.schabi.newpipe.extractor.localization.DateWrapper;
import org.schabi.newpipe.extractor.stream.StreamInfo;

/** Experimental JSON-lines bridge for the yt-discover NewPipeExtractor benchmark. */
public final class NewPipeBenchmarkBridge {
    private static final Gson GSON = new Gson();
    private static final String USER_AGENT = "yt-media-tools NewPipeExtractor benchmark/1";

    private NewPipeBenchmarkBridge() {}

    public static void main(final String[] args) {
        if (args.length == 0) {
            System.err.println("usage: yt-media-tools-newpipe-bridge VIDEO_ID [...]");
            System.exit(2);
        }
        NewPipe.init(new JavaHttpDownloader());
        for (final String videoId : args) {
            final long started = System.nanoTime();
            final Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", videoId);
            try {
                final StreamInfo info = StreamInfo.getInfo("https://www.youtube.com/watch?v=" + videoId);
                row.put("ok", true);
                row.put("title", info.getName());
                row.put("description", info.getDescription().getContent());
                row.put("uploader_name", info.getUploaderName());
                row.put("uploader_url", info.getUploaderUrl());
                row.put("duration", info.getDuration());
                row.put("view_count", info.getViewCount());
                final DateWrapper uploadDate = info.getUploadDate();
                row.put("upload_date", uploadDate == null ? null : uploadDate.offsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
                row.put("upload_date_approximate", uploadDate != null && uploadDate.isApproximation());
                row.put("category", info.getCategory());
                row.put("stream_type", String.valueOf(info.getStreamType()));
                row.put("keywords", info.getTags());
                row.put("content_availability", String.valueOf(info.getContentAvailability()));
                row.put("uploader_verified", info.isUploaderVerified());
                row.put("short_form", info.isShortFormContent());
            } catch (final Exception exception) {
                row.put("ok", false);
                row.put("error_type", exception.getClass().getSimpleName());
                row.put("error", exception.getMessage() == null ? exception.toString() : exception.getMessage());
            }
            row.put("elapsed_ms", (System.nanoTime() - started) / 1_000_000.0);
            System.out.println(GSON.toJson(row));
        }
    }

    private static final class JavaHttpDownloader extends Downloader {
        private final HttpClient client = HttpClient.newBuilder()
                .followRedirects(HttpClient.Redirect.NORMAL)
                .connectTimeout(Duration.ofSeconds(30))
                .build();

        @Override
        public Response execute(final Request request) throws IOException {
            final HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(request.url()))
                    .timeout(Duration.ofSeconds(30));
            final Map<String, List<String>> headers = request.headers();
            if (headers != null) {
                headers.forEach((name, values) -> values.forEach(value -> builder.header(name, value)));
            }
            if (headers == null || headers.keySet().stream().noneMatch(name -> name.equalsIgnoreCase("User-Agent"))) {
                builder.header("User-Agent", USER_AGENT);
            }
            final byte[] data = request.dataToSend();
            final HttpRequest.BodyPublisher body = data == null
                    ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofByteArray(data);
            builder.method(request.httpMethod(), body);
            try {
                final HttpResponse<byte[]> response = client.send(builder.build(), HttpResponse.BodyHandlers.ofByteArray());
                final Map<String, List<String>> responseHeaders = new LinkedHashMap<>();
                response.headers().map().forEach((name, values) -> responseHeaders.put(name, new ArrayList<>(values)));
                return new Response(
                        response.statusCode(),
                        "HTTP " + response.statusCode(),
                        responseHeaders,
                        new String(response.body(), StandardCharsets.UTF_8),
                        response.uri().toString());
            } catch (final InterruptedException exception) {
                Thread.currentThread().interrupt();
                throw new IOException("NewPipeExtractor benchmark request interrupted", exception);
            }
        }
    }
}
