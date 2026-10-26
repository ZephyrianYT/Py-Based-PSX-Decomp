#version 330 core
// PS1-style fragment shader.
// Reproduces: nearest texel fetch, PS1 texture modulation (tex * col / 128),
// 1-bit cut-out transparency, per-vertex fog, and 15-bit output with the
// hardware 4x4 ordered dither. Render to a 320x240 target and upscale with
// nearest filtering. See ref/look/recreating-the-look.md.

noperspective in vec2 vUV;
in vec3 vColor;
in float vFog;

uniform sampler2D uTexture;      // set GL_NEAREST min/mag, no mipmaps
uniform bool  uTextured = true;
uniform vec3  uFogColor = vec3(0.0); // GTE FC
uniform bool  uDither   = true;

out vec4 fragColor;

// Exact PS1 GPU dither table (added to 8-bit channels before >>3).
const float DITHER[16] = float[16](
    -4.0,  0.0, -3.0,  1.0,
     2.0, -2.0,  3.0, -1.0,
    -3.0,  1.0, -4.0,  0.0,
     3.0, -1.0,  2.0, -2.0
);

vec3 quantize15(vec3 c, ivec2 pix) {
    vec3 c8 = c * 255.0;
    if (uDither) {
        c8 += DITHER[(pix.y & 3) * 4 + (pix.x & 3)];
    }
    c8 = clamp(c8, 0.0, 255.0);
    vec3 c5 = floor(c8 / 8.0);         // truncate to 5 bits like the GPU
    return c5 / 31.0;
}

void main() {
    vec3 color = vColor * 2.0;         // 0.5 vertex colour == unmodified texel
    if (uTextured) {
        // texelFetch-style nearest lookup without relying on sampler state.
        ivec2 size = textureSize(uTexture, 0);
        ivec2 texel = ivec2(floor(fract(vUV) * vec2(size)));
        vec4 t = texelFetch(uTexture, texel, 0);
        if (t.a < 0.5) discard;        // PS1 colour 0x0000 = transparent
        color *= t.rgb;
    }
    color = mix(color, uFogColor, vFog);
    fragColor = vec4(quantize15(clamp(color, 0.0, 1.0), ivec2(gl_FragCoord.xy)), 1.0);
}
