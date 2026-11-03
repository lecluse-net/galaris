# Read configuration as data, never execute/source it or print its values.
function sensitive(key) {
    return toupper(key) ~ /(PASSWORD|SECRET|TOKEN|CREDENTIAL|PRIVATE_KEY|API_KEY|MASTER_KEY)/
}
function remember(value,    position) {
    if (!length(value) || (value in secrets)) return
    secrets[value] = 1
    # Replace longer overlapping credentials first.
    position = ++secret_count
    while (position > 1 && length(secret_values[position - 1]) < length(value)) {
        secret_values[position] = secret_values[position - 1]
        position--
    }
    secret_values[position] = value
}
function replace_literal(line, value,    result, position) {
    result = ""
    while ((position = index(line, value)) > 0) {
        result = result substr(line, 1, position - 1) "***"
        line = substr(line, position + length(value))
    }
    return result line
}
function redact_urls(line,    result, credential, scheme, start, size) {
    result = ""
    while (match(line, /[A-Za-z][A-Za-z0-9+.-]*:\/\/[^[:space:]\/@]+@/)) {
        start = RSTART
        size = RLENGTH
        credential = substr(line, start, size)
        scheme = substr(credential, 1, index(credential, "://") + 2)
        result = result substr(line, 1, start - 1) scheme "***@"
        line = substr(line, start + size)
    }
    return result line
}
function redact_fields(line,    result, credential, start, size) {
    result = ""
    while (match(tolower(line), /[a-z_0-9-]*(password|passwd|secret|token|credential|api[_-]?key|private[_-]?key|authorization|cookie)[a-z_0-9-]*["']*[[:space:]]*[:=][[:space:]]*("([^"\\]|\\.)*"|'([^'\\]|\\.)*'|(bearer|basic)[[:space:]]+[^[:space:],;]+|[^[:space:],;]+)/)) {
        start = RSTART
        size = RLENGTH
        credential = substr(line, start, size)
        match(credential, /[:=]/)
        result = result substr(line, 1, start - 1) substr(credential, 1, RSTART) "***"
        line = substr(line, start + size)
    }
    return result line
}
function redact_bearer(line,    result, start, size) {
    result = ""
    while (match(tolower(line), /bearer[[:space:]]+[^[:space:],;"']+/)) {
        start = RSTART
        size = RLENGTH
        result = result substr(line, 1, start - 1) "Bearer ***"
        line = substr(line, start + size)
    }
    return result line
}
BEGIN {
    for (key in ENVIRON) if (sensitive(key)) remember(ENVIRON[key])
    status = (getline configuration < ".env")
    while (status > 0) {
        if (configuration ~ /^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z_0-9]*[[:space:]]*=/) {
            separator = index(configuration, "=")
            key = substr(configuration, 1, separator - 1)
            if (sensitive(key)) {
                value = substr(configuration, separator + 1)
                sub(/^[[:space:]]+/, "", value)
                sub(/[[:space:]]+$/, "", value)
                quote = substr(value, 1, 1)
                if (quote == "\"" || quote == "'") {
                    value = substr(value, 2)
                    end = index(value, quote)
                    if (end) value = substr(value, 1, end - 1)
                } else {
                    sub(/[[:space:]]+#.*/, "", value)
                }
                remember(value)
            }
        }
        status = (getline configuration < ".env")
    }
    close(".env")
    if (status < 0) {
        print "Unable to read secret configuration for update log redaction." > "/dev/stderr"
        exit 74
    }
}
{
    line = $0
    if (line ~ /-----BEGIN [^-]*PRIVATE KEY-----/) private_key = 1
    if (private_key) {
        if (line ~ /-----END [^-]*PRIVATE KEY-----/) private_key = 0
        print "[redacted private key]"
        fflush()
        next
    }
    # Literal replacement handles regex metacharacters in secrets safely.
    for (position = 1; position <= secret_count; position++) line = replace_literal(line, secret_values[position])
    line = redact_urls(line)
    # Credentials generated inside containers may not exist in the host .env.
    print redact_bearer(redact_fields(line))
    fflush()
}
