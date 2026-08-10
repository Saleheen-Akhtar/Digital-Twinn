function handler(event) {
    var request = event.request;
    var uri = request.uri;

    // Never touch API proxy routes — they must pass through to the API origin untouched.
    if (uri.indexOf('/api/') === 0 || uri.indexOf('/auth/') === 0) {
        return request;
    }

    // Any path with a file extension (css/js/png/svg/...) is a real object — leave it.
    if (uri.indexOf('.') !== -1) {
        return request;
    }

    // SPA deep link: rewrite /foo or /foo/ to /foo/index.html (Next static export layout).
    var trimmed = uri;
    if (trimmed.charAt(trimmed.length - 1) === '/') {
        trimmed = trimmed.slice(0, -1);
    }
    request.uri = trimmed + '/index.html';
    return request;
}