# External image import

Scope: implement M0's requirement that corrections accept pictures made elsewhere.
This extends the runnable slice; it does not mark M1 or M5 complete.

## Flow

1. The client requests an owner-bound, expiring upload intent with filename and byte size.
2. It PUTs bytes to the returned storage URL.
3. Completion creates one idempotent `upload` job in the chosen conversation.
4. The worker verifies and normalizes PNG, JPEG, or WebP to PNG, applies EXIF orientation,
   builds derivatives, and stores a lineage root. No provider is called.
5. The image appears in conversation history and becomes the composer's edit source.
   Existing whole-image and region edit paths handle subsequent requests.

Files are limited to 50 MiB and 32 megapixels. Animated images and undecodable files are
rejected. Alpha is flattened on white for the current RGB editing pipeline, with a visible
event explaining that choice. User filenames are display metadata, never storage paths or
model instructions. Uploaded originals are normalized; source pixels are not resized.

## Local storage boundary

The metadata endpoints do not receive image bodies. `/_uploads/` is a local-only storage
shim, matching the existing `/_blobs/` development exception to M0's byte-proxy rule.
It streams bounded bodies into private staging files, requires the owner's identity,
refuses overwrites, and honors intent expiry. A future cloud storage implementation must
return a signed direct-upload URL and remove the local shim. No Azure resources are used.

## Reliability and ownership

Completion and queue insertion share a database transaction. Repeated completion returns
the same job. An upload belongs to exactly one account; all operations repeat that check.
The new upload table is additive and does not alter existing user or image data. Abandoned
staging files still need lifecycle cleanup before production, like existing orphan blobs.

## UI

Use the existing composer, Radix buttons, theme tokens, and image preview. Add an attach
button, drop target, clipboard image paste, preparation status, and useful errors. Imported
images have an explicit upload label, no generation charge, and no rerun action. On reload,
the root remains in the conversation and can be selected for editing again.

## Verification

Exercise import, ownership, expiry, bounded transfer, duplicate completion, invalid image
handling, EXIF orientation, and an imported-image region edit through the offline API and
worker. Check TypeScript, Python lint/format, and the full offline suite. Inspect the UI in
the browser using an isolated local data directory and the echo provider.
