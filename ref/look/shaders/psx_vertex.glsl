#version 330 core
// PS1-style vertex shader.
// Reproduces: integer screen-space vertex positions (jitter), affine texture
// coordinates, per-vertex directional lighting (GTE NCDS-like) and per-vertex
// depth-cue fog. See ref/look/recreating-the-look.md.

layout(location = 0) in vec3 aPosition;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec2 aUV;
layout(location = 3) in vec3 aColor;      // baked vertex colour, 0..1 (0.5 = neutral, like 0x80)

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;

uniform vec2  uSnapResolution = vec2(320.0, 240.0); // virtual PS1 framebuffer
uniform bool  uUseLighting    = true;
uniform vec3  uLightDir[3];                       // world-space, pointing *towards* the light
uniform vec3  uLightColor[3];
uniform vec3  uAmbient        = vec3(0.25);       // GTE BK
uniform float uFogNear        = 8.0;              // view-space distance where fog starts
uniform float uFogFar         = 40.0;             // distance where fog is total (GTE IR0 = 0x1000)

noperspective out vec2 vUV;      // affine: interpolated linearly in screen space
out vec3 vColor;                 // Gouraud colour, already lit
out float vFog;                  // per-vertex depth cue factor 0..1

void main() {
    vec4 world = uModel * vec4(aPosition, 1.0);
    vec4 view  = uView * world;
    vec4 clip  = uProj * view;

    // --- Vertex snapping: integer pixel positions on the virtual framebuffer.
    vec2 halfRes = uSnapResolution * 0.5;
    vec2 ndc = clip.xy / clip.w;
    ndc = floor(ndc * halfRes + 0.5) / halfRes;
    clip.xy = ndc * clip.w;
    gl_Position = clip;

    vUV = aUV;

    // --- Per-vertex lighting: BK + sum(lightColor * max(0, N.L)), times vertex colour.
    vec3 lit = vec3(1.0);
    if (uUseLighting) {
        vec3 n = normalize(mat3(uModel) * aNormal);
        lit = uAmbient;
        for (int i = 0; i < 3; ++i) {
            lit += uLightColor[i] * max(dot(n, normalize(uLightDir[i])), 0.0);
        }
    }
    vColor = aColor * lit;   // fragment multiplies by 2 so 0.5 == neutral, mirroring PS1 0x80

    // --- Depth cue: linear in view distance, evaluated per vertex like the GTE.
    float dist = length(view.xyz);
    vFog = clamp((dist - uFogNear) / (uFogFar - uFogNear), 0.0, 1.0);
}
