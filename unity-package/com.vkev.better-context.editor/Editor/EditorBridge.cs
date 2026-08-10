using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace VKev.BetterContext
{
    [InitializeOnLoad]
    public static class EditorBridge
    {
        public const string BridgeVersion = "1.6.0";
        public const string SnapshotSchema = "1.0.0";

        private static readonly string ProjectRoot =
            Directory.GetParent(Application.dataPath)?.FullName ?? string.Empty;
        private static readonly string DefaultRequestPath = Path.Combine(
            ProjectRoot,
            ".better-context",
            "editor-request.json");
        private static double _nextPoll;
        private static string _lastNonce = string.Empty;

        static EditorBridge()
        {
            EditorApplication.update += Poll;
        }

        public static void Export()
        {
            string requestPath = GetCommandLineValue("-betterContextRequest") ?? DefaultRequestPath;
            ExportRequest(requestPath, "batch");
        }

        public static void ExportRequestForTests(string requestPath)
        {
            ExportRequest(requestPath, "open");
        }

        private static void Poll()
        {
            if (EditorApplication.timeSinceStartup < _nextPoll)
            {
                return;
            }
            _nextPoll = EditorApplication.timeSinceStartup + 0.5d;
            if (!File.Exists(DefaultRequestPath))
            {
                return;
            }
            try
            {
                Request request = ReadRequest(DefaultRequestPath);
                if (request == null || string.IsNullOrEmpty(request.nonce) || request.nonce == _lastNonce)
                {
                    return;
                }
                _lastNonce = request.nonce;
                ExportRequest(DefaultRequestPath, "open");
            }
            catch (Exception exception)
            {
                Debug.LogWarning($"Better Context Editor request failed: {exception.Message}");
            }
        }

        private static void ExportRequest(string requestPath, string mode)
        {
            Request request = ReadRequest(requestPath);
            if (request == null)
            {
                throw new InvalidOperationException($"Invalid Better Context request: {requestPath}");
            }
            EditorSnapshot snapshot = BuildSnapshot(request, mode);
            string responsePath = string.IsNullOrEmpty(request.response_path)
                ? Path.Combine(ProjectRoot, ".better-context", "editor-snapshot.json")
                : request.response_path;
            AtomicWrite(responsePath, JsonUtility.ToJson(snapshot, true));
            Debug.Log($"Better Context Editor snapshot exported to {responsePath}");
        }

        private static Request ReadRequest(string path)
        {
            if (!File.Exists(path))
            {
                return null;
            }
            return JsonUtility.FromJson<Request>(File.ReadAllText(path));
        }

        private static EditorSnapshot BuildSnapshot(Request request, string mode)
        {
            EditorSnapshot snapshot = new EditorSnapshot
            {
                schema_version = SnapshotSchema,
                bridge_version = BridgeVersion,
                unity_version = Application.unityVersion,
                mode = mode,
                nonce = request.nonce,
                source_hash = request.source_hash,
                package_lock_hash = request.package_lock_hash,
                generated_at = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                status = "ok",
            };

            ExportScripts(snapshot);
            string[] paths = AssetDatabase.GetAllAssetPaths()
                .Where(path => path.StartsWith("Assets/", StringComparison.Ordinal)
                    || path.StartsWith("Packages/", StringComparison.Ordinal))
                .OrderBy(path => path, StringComparer.Ordinal)
                .ToArray();
            snapshot.coverage.assets_scanned = paths.Length;
            foreach (string path in paths)
            {
                try
                {
                    AssetFact asset = ExportAsset(path);
                    if (asset == null)
                    {
                        continue;
                    }
                    snapshot.assets.Add(asset);
                    snapshot.coverage.assets_exported++;
                }
                catch (Exception exception)
                {
                    snapshot.errors.Add(new ExportError { path = path, message = exception.Message });
                    snapshot.coverage.errors++;
                }
            }
            snapshot.coverage.mono_scripts = snapshot.scripts.Count;
            return snapshot;
        }

        private static void ExportScripts(EditorSnapshot snapshot)
        {
            foreach (string guid in AssetDatabase.FindAssets("t:MonoScript").OrderBy(value => value))
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                MonoScript script = AssetDatabase.LoadAssetAtPath<MonoScript>(path);
                if (script == null)
                {
                    continue;
                }
                Type type = script.GetClass();
                AssetDatabase.TryGetGUIDAndLocalFileIdentifier(script, out string resolvedGuid, out long localId);
                snapshot.scripts.Add(new ScriptFact
                {
                    guid = string.IsNullOrEmpty(resolvedGuid) ? guid : resolvedGuid,
                    path = path,
                    local_id = localId,
                    qualified_type = type?.FullName ?? string.Empty,
                    assembly = type?.Assembly.GetName().Name ?? string.Empty,
                    base_type = type?.BaseType?.FullName ?? string.Empty,
                    boundary = Boundary(path),
                    resolved = type != null,
                });
            }
        }

        private static AssetFact ExportAsset(string path)
        {
            AssetImporter importer = AssetImporter.GetAtPath(path);
            UnityEngine.Object main = AssetDatabase.LoadMainAssetAtPath(path);
            string kind = AssetKind(path, importer, main);
            if (string.IsNullOrEmpty(kind))
            {
                return null;
            }
            AssetFact asset = new AssetFact
            {
                path = path,
                guid = AssetDatabase.AssetPathToGUID(path),
                kind = kind,
                type_name = main?.GetType().FullName ?? importer?.GetType().FullName ?? string.Empty,
                name = main?.name ?? Path.GetFileNameWithoutExtension(path),
                boundary = Boundary(path),
                importer_type = importer?.GetType().FullName ?? string.Empty,
            };
            asset.dependencies.AddRange(
                AssetDatabase.GetDependencies(path, false)
                    .Where(value => value != path && !value.EndsWith(".meta", StringComparison.OrdinalIgnoreCase))
                    .OrderBy(value => value, StringComparer.Ordinal));

            if (importer is TextureImporter textureImporter)
            {
                ExportTexture(asset, textureImporter, main as Texture);
            }
            else if (importer is AudioImporter audioImporter)
            {
                ExportAudio(asset, audioImporter, main);
            }
            else
            {
                ExportGenericAsset(asset, main, importer);
            }
            if (kind == "sprite_atlas")
            {
                ExportSpriteAtlas(asset, main);
            }
            return asset;
        }

        private static string AssetKind(string path, AssetImporter importer, UnityEngine.Object main)
        {
            if (importer is TextureImporter)
            {
                if (main is Cubemap)
                {
                    return "cubemap";
                }
                return "texture";
            }
            if (importer is AudioImporter)
            {
                return "audio_clip";
            }
            string importerName = importer?.GetType().Name ?? string.Empty;
            if (importerName == "VideoClipImporter")
            {
                return "video_clip";
            }
            string typeName = main?.GetType().FullName ?? string.Empty;
            if (typeName.Contains("SpriteAtlas", StringComparison.Ordinal)) return "sprite_atlas";
            if (typeName == "UnityEngine.Shader") return "shader";
            if (typeName == "UnityEngine.RenderTexture") return "render_texture";
            if (typeName == "UnityEngine.Font" || typeName.Contains("TMP_FontAsset", StringComparison.Ordinal)) return "font";
            if (typeName == "UnityEngine.TerrainData") return "terrain_data";
            if (typeName == "UnityEngine.TerrainLayer") return "terrain_layer";
            if (typeName == "UnityEngine.PhysicMaterial") return "physic_material";
            if (typeName == "UnityEngine.PhysicsMaterial2D") return "physics_material_2d";
            if (typeName.Contains("AudioMixer", StringComparison.Ordinal)) return "audio_mixer";
            if (typeName.Contains("TimelineAsset", StringComparison.Ordinal)) return "timeline";
            if (typeName == "UnityEngine.LightingSettings") return "lighting_settings";
            if (typeName.Contains("NavMeshData", StringComparison.Ordinal)) return "navmesh_data";
            string extension = Path.GetExtension(path).ToLowerInvariant();
            if (extension == ".shadergraph" || extension == ".shadersubgraph") return "shader";
            return string.Empty;
        }

        private static void ExportTexture(AssetFact asset, TextureImporter importer, Texture texture)
        {
            TextureImporterSettings textureSettings = new TextureImporterSettings();
            importer.ReadTextureSettings(textureSettings);
            importer.GetSourceTextureWidthAndHeight(out int sourceWidth, out int sourceHeight);
            Add(asset, "source_width", sourceWidth);
            Add(asset, "source_height", sourceHeight);
            Add(asset, "width", texture?.width ?? 0);
            Add(asset, "height", texture?.height ?? 0);
            Add(asset, "source_format", Path.GetExtension(asset.path).TrimStart('.').ToUpperInvariant());
            Add(asset, "imported_format", texture is Texture2D texture2D ? texture2D.format.ToString() : string.Empty);
            Add(asset, "alpha_source", importer.alphaSource);
            Add(asset, "alpha_is_transparency", importer.alphaIsTransparency);
            Add(asset, "s_rgb", importer.sRGBTexture);
            Add(asset, "readable", importer.isReadable);
            Add(asset, "mipmaps", importer.mipmapEnabled);
            Add(asset, "streaming_mipmaps", importer.streamingMipmaps);
            Add(asset, "texture_type", importer.textureType);
            Add(asset, "texture_shape", importer.textureShape);
            Add(asset, "filter_mode", importer.filterMode);
            Add(asset, "wrap_mode", importer.wrapMode);
            Add(asset, "aniso", importer.anisoLevel);
            Add(asset, "npot_scale", importer.npotScale);
            Add(asset, "compression", importer.textureCompression);
            Add(asset, "crunched_compression", importer.crunchedCompression);
            Add(asset, "compression_quality", importer.compressionQuality);
            Add(asset, "max_texture_size", importer.maxTextureSize);
            Add(asset, "sprite_mode", importer.spriteImportMode);
            Add(asset, "pixels_per_unit", importer.spritePixelsPerUnit);
            Add(asset, "sprite_mesh_type", textureSettings.spriteMeshType);
            Add(asset, "sprite_pivot", importer.spritePivot);
            Add(asset, "sprite_border", importer.spriteBorder);
            foreach (string platform in new[] { "DefaultTexturePlatform", "Standalone", "iPhone", "Android" })
            {
                TextureImporterPlatformSettings settings = importer.GetPlatformTextureSettings(platform);
                string prefix = $"platform.{platform}.";
                Add(asset, prefix + "overridden", settings.overridden);
                Add(asset, prefix + "max_texture_size", settings.maxTextureSize);
                Add(asset, prefix + "format", settings.format);
                Add(asset, prefix + "compression_quality", settings.compressionQuality);
                Add(asset, prefix + "allows_alpha_splitting", settings.allowsAlphaSplitting);
            }

            foreach (UnityEngine.Object loaded in AssetDatabase.LoadAllAssetsAtPath(asset.path))
            {
                if (!(loaded is Sprite sprite))
                {
                    continue;
                }
                AssetDatabase.TryGetGUIDAndLocalFileIdentifier(sprite, out _, out long localId);
                SubassetFact fact = new SubassetFact
                {
                    name = sprite.name,
                    type_name = sprite.GetType().FullName,
                    local_id = localId,
                    sprite_id = ReadSpriteId(sprite),
                };
                Add(fact, "rect", sprite.rect);
                Add(fact, "pivot", sprite.pivot);
                Add(fact, "border", sprite.border);
                Add(fact, "pixels_per_unit", sprite.pixelsPerUnit);
                Add(fact, "mesh_type", textureSettings.spriteMeshType);
                Add(fact, "physics_shape_count", sprite.GetPhysicsShapeCount());
                Add(fact, "secondary_textures", ReadSecondaryTextureNames(importer));
                asset.subassets.Add(fact);
            }
        }

        private static void ExportAudio(AssetFact asset, AudioImporter importer, UnityEngine.Object main)
        {
            Add(asset, "force_to_mono", importer.forceToMono);
            Add(asset, "load_in_background", importer.loadInBackground);
            Add(asset, "ambisonic", importer.ambisonic);
            AudioImporterSampleSettings settings = importer.defaultSampleSettings;
            Add(asset, "preload_audio_data", settings.preloadAudioData);
            Add(asset, "load_type", settings.loadType);
            Add(asset, "compression_format", settings.compressionFormat);
            Add(asset, "quality", settings.quality);
            Add(asset, "sample_rate_setting", settings.sampleRateSetting);
            Add(asset, "sample_rate_override", settings.sampleRateOverride);
            if (main != null)
            {
                AddReflected(asset, main, "length", "channels", "frequency", "samples", "loadState");
            }
        }

        private static void ExportGenericAsset(AssetFact asset, UnityEngine.Object main, AssetImporter importer)
        {
            if (main != null)
            {
                AddReflected(
                    asset,
                    main,
                    "width",
                    "height",
                    "dimension",
                    "length",
                    "frameCount",
                    "frameRate",
                    "audioTrackCount",
                    "vertexCount",
                    "terrainLayers",
                    "detailWidth",
                    "detailHeight",
                    "heightmapResolution",
                    "alphamapResolution",
                    "size");
            }
            if (importer != null)
            {
                AddReflected(
                    asset,
                    importer,
                    "isReadable",
                    "quality",
                    "transcode",
                    "flipHorizontal",
                    "flipVertical",
                    "importAudio",
                    "keepAlpha",
                    "linearColorSpace");
            }
        }

        private static void ExportSpriteAtlas(AssetFact asset, UnityEngine.Object main)
        {
            if (main == null)
            {
                return;
            }
            Type extensions = FindType("UnityEditor.U2D.SpriteAtlasExtensions");
            if (extensions == null)
            {
                return;
            }
            object[] packables = InvokeStatic(extensions, "GetPackables", main) as object[];
            if (packables != null)
            {
                Add(asset, "packable_count", packables.Length);
                Add(asset, "packables", string.Join(",", packables.OfType<UnityEngine.Object>()
                    .Select(AssetDatabase.GetAssetPath).Where(value => !string.IsNullOrEmpty(value))));
            }
            Add(asset, "is_variant", ReadProperty(main, "isVariant"));
            object master = InvokeStatic(extensions, "GetMasterAtlas", main);
            if (master is UnityEngine.Object masterObject)
            {
                Add(asset, "master_atlas", AssetDatabase.GetAssetPath(masterObject));
            }
            object packing = InvokeStatic(extensions, "GetPackingSettings", main);
            if (packing != null)
            {
                AddReflected(
                    asset,
                    packing,
                    "blockOffset",
                    "enableRotation",
                    "enableTightPacking",
                    "padding");
            }
            Add(asset, "sprite_count", ReadProperty(main, "spriteCount"));
        }

        private static string ReadSpriteId(Sprite sprite)
        {
            MethodInfo method = sprite.GetType().GetMethod("GetSpriteID", BindingFlags.Instance | BindingFlags.Public);
            object value = method?.Invoke(sprite, null);
            if (value != null)
            {
                return value.ToString();
            }
            SerializedObject serialized = new SerializedObject(sprite);
            foreach (string propertyName in new[] { "m_SpriteID", "m_RD.m_SpriteID" })
            {
                SerializedProperty property = serialized.FindProperty(propertyName);
                if (property != null && property.propertyType == SerializedPropertyType.String)
                {
                    return property.stringValue;
                }
            }
            return string.Empty;
        }

        private static string ReadSecondaryTextureNames(TextureImporter importer)
        {
            MethodInfo method = importer.GetType().GetMethod("GetSecondaryTextures", Type.EmptyTypes);
            if (!(method?.Invoke(importer, null) is IEnumerable values))
            {
                return string.Empty;
            }
            List<string> names = new List<string>();
            foreach (object value in values)
            {
                object name = ReadMember(value, "name");
                if (name != null)
                {
                    names.Add(name.ToString());
                }
            }
            return string.Join(",", names);
        }

        private static void AddReflected(AssetFact asset, object source, params string[] members)
        {
            foreach (string member in members)
            {
                object value = ReadMember(source, member);
                if (value != null)
                {
                    Add(asset, member, value);
                }
            }
        }

        private static object ReadProperty(object source, string name)
        {
            return source?.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public)?.GetValue(source);
        }

        private static object ReadMember(object source, string name)
        {
            if (source == null) return null;
            Type type = source.GetType();
            PropertyInfo property = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public);
            if (property != null && property.GetIndexParameters().Length == 0)
            {
                return property.GetValue(source);
            }
            return type.GetField(name, BindingFlags.Instance | BindingFlags.Public)?.GetValue(source);
        }

        private static Type FindType(string fullName)
        {
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type type = assembly.GetType(fullName, false);
                if (type != null) return type;
            }
            return null;
        }

        private static object InvokeStatic(Type type, string methodName, object argument)
        {
            MethodInfo method = type.GetMethods(BindingFlags.Static | BindingFlags.Public)
                .FirstOrDefault(value => value.Name == methodName && value.GetParameters().Length == 1);
            return method?.Invoke(null, new[] { argument });
        }

        private static void Add(AssetFact asset, string name, object value)
        {
            asset.facts.Add(new NamedFact { name = name, value = Format(value) });
        }

        private static void Add(SubassetFact asset, string name, object value)
        {
            asset.facts.Add(new NamedFact { name = name, value = Format(value) });
        }

        private static string Format(object value)
        {
            if (value == null) return string.Empty;
            if (value is bool boolean) return boolean ? "true" : "false";
            if (value is float single) return single.ToString("R", CultureInfo.InvariantCulture);
            if (value is double number) return number.ToString("R", CultureInfo.InvariantCulture);
            if (value is Vector2 vector2)
                return "{x:" + Number(vector2.x) + ",y:" + Number(vector2.y) + "}";
            if (value is Vector3 vector3)
                return "{x:" + Number(vector3.x) + ",y:" + Number(vector3.y)
                    + ",z:" + Number(vector3.z) + "}";
            if (value is Vector4 vector4)
                return "{x:" + Number(vector4.x) + ",y:" + Number(vector4.y)
                    + ",z:" + Number(vector4.z) + ",w:" + Number(vector4.w) + "}";
            if (value is Rect rect)
                return "{x:" + Number(rect.x) + ",y:" + Number(rect.y)
                    + ",width:" + Number(rect.width) + ",height:" + Number(rect.height) + "}";
            return Convert.ToString(value, CultureInfo.InvariantCulture) ?? string.Empty;
        }

        private static string Number(float value)
        {
            return value.ToString("R", CultureInfo.InvariantCulture);
        }

        private static string Boundary(string path)
        {
            if (path.StartsWith("Packages/", StringComparison.Ordinal)) return "package";
            string[] vendorRoots =
            {
                "Assets/GoogleMobileAds/",
                "Assets/Plugin/",
                "Assets/Plugins/",
                "Assets/TextMesh Pro/",
                "Assets/Tools/",
            };
            return vendorRoots.Any(root => path.StartsWith(root, StringComparison.Ordinal))
                ? "vendor"
                : "project";
        }

        private static string GetCommandLineValue(string key)
        {
            string[] arguments = Environment.GetCommandLineArgs();
            for (int index = 0; index < arguments.Length - 1; index++)
            {
                if (string.Equals(arguments[index], key, StringComparison.Ordinal))
                {
                    return arguments[index + 1];
                }
            }
            return null;
        }

        private static void AtomicWrite(string path, string content)
        {
            string directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllText(temporary, content);
            if (File.Exists(path))
            {
                string backup = path + "." + Guid.NewGuid().ToString("N") + ".bak";
                File.Replace(temporary, path, backup);
                File.Delete(backup);
            }
            else
            {
                File.Move(temporary, path);
            }
        }

        [Serializable]
        private sealed class Request
        {
            public string schema_version;
            public string bridge_version;
            public string project_root;
            public string mode;
            public string nonce;
            public string source_hash;
            public string package_lock_hash;
            public string response_path;
        }

        [Serializable]
        private sealed class EditorSnapshot
        {
            public string schema_version;
            public string bridge_version;
            public string unity_version;
            public string mode;
            public string nonce;
            public string source_hash;
            public string package_lock_hash;
            public string generated_at;
            public string status;
            public Coverage coverage = new Coverage();
            public List<AssetFact> assets = new List<AssetFact>();
            public List<ScriptFact> scripts = new List<ScriptFact>();
            public List<ExportError> errors = new List<ExportError>();
        }

        [Serializable]
        private sealed class Coverage
        {
            public int assets_scanned;
            public int assets_exported;
            public int mono_scripts;
            public int errors;
        }

        [Serializable]
        private sealed class AssetFact
        {
            public string path;
            public string guid;
            public string kind;
            public string type_name;
            public string name;
            public string boundary;
            public string importer_type;
            public List<string> dependencies = new List<string>();
            public List<NamedFact> facts = new List<NamedFact>();
            public List<SubassetFact> subassets = new List<SubassetFact>();
        }

        [Serializable]
        private sealed class SubassetFact
        {
            public string name;
            public string type_name;
            public long local_id;
            public string sprite_id;
            public List<NamedFact> facts = new List<NamedFact>();
        }

        [Serializable]
        private sealed class NamedFact
        {
            public string name;
            public string value;
        }

        [Serializable]
        private sealed class ScriptFact
        {
            public string guid;
            public string path;
            public long local_id;
            public string qualified_type;
            public string assembly;
            public string base_type;
            public string boundary;
            public bool resolved;
        }

        [Serializable]
        private sealed class ExportError
        {
            public string path;
            public string message;
        }
    }
}
