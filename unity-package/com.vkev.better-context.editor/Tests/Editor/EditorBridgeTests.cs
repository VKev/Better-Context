using System;
using System.IO;
using System.Linq;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace VKev.BetterContext.Tests
{
    public sealed class EditorBridgeTests
    {
        private const string AssetPath = "Assets/BetterContextEditorBridgeTest.png";

        [SetUp]
        public void SetUp()
        {
            Texture2D texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            texture.SetPixels(new[] { Color.red, Color.green, Color.blue, Color.white });
            texture.Apply();
            File.WriteAllBytes(AssetPath, texture.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(texture);
            AssetDatabase.ImportAsset(AssetPath, ImportAssetOptions.ForceSynchronousImport);
            TextureImporter importer = (TextureImporter)AssetImporter.GetAtPath(AssetPath);
            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode = SpriteImportMode.Single;
            importer.spritePixelsPerUnit = 100f;
            importer.mipmapEnabled = false;
            importer.SaveAndReimport();
        }

        [TearDown]
        public void TearDown()
        {
            AssetDatabase.DeleteAsset(AssetPath);
        }

        [Test]
        public void LoadAllAssetsReturnsSpriteWithStableLocalId()
        {
            Sprite sprite = AssetDatabase.LoadAllAssetsAtPath(AssetPath).OfType<Sprite>().Single();

            bool resolved = AssetDatabase.TryGetGUIDAndLocalFileIdentifier(
                sprite,
                out string guid,
                out long localId);

            Assert.That(resolved, Is.True);
            Assert.That(guid, Has.Length.EqualTo(32));
            Assert.That(localId, Is.Not.Zero);
        }

        [Test]
        public void MonoScriptGetClassResolvesQualifiedType()
        {
            BridgeProbe probe = ScriptableObject.CreateInstance<BridgeProbe>();
            MonoScript script = MonoScript.FromScriptableObject(probe);

            Type resolved = script.GetClass();

            UnityEngine.Object.DestroyImmediate(probe);
            Assert.That(resolved, Is.EqualTo(typeof(BridgeProbe)));
        }

        [Test]
        public void ExportsUiShadersMaterialsAndCustomAssetReferences()
        {
            const string folder = "Assets/BetterContextExtendedTest";
            AssetDatabase.CreateFolder("Assets", "BetterContextExtendedTest");
            try
            {
                File.WriteAllText(folder + "/Test.shader",
                    "Shader \"BetterContext/Test\" { Properties { _Tint (\"Tint\", Color) = (1,1,1,1) } "
                    + "SubShader { Pass {} } }");
                File.WriteAllText(folder + "/Panel.uss", ".panel { color: red; }");
                File.WriteAllText(folder + "/Panel.uxml",
                    "<ui:UXML xmlns:ui=\"UnityEngine.UIElements\"><Style src=\"Panel.uss\"/>"
                    + "<ui:Label name=\"title\" text=\"Title\"/></ui:UXML>");
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                Shader shader = AssetDatabase.LoadAssetAtPath<Shader>(folder + "/Test.shader");
                Assert.That(shader, Is.Not.Null);
                Material material = new Material(shader);
                material.SetColor("_Tint", Color.green);
                AssetDatabase.CreateAsset(material, folder + "/Test.mat");
                BridgeProbe probe = ScriptableObject.CreateInstance<BridgeProbe>();
                probe.icon = AssetDatabase.LoadAssetAtPath<Texture2D>(AssetPath);
                AssetDatabase.CreateAsset(probe, folder + "/Custom.asset");
                AssetDatabase.SaveAssets();

                string directory = Path.Combine("Library", "BetterContextEditorBridgeTests");
                Directory.CreateDirectory(directory);
                string requestPath = Path.GetFullPath(Path.Combine(directory, "extended-request.json"));
                string responsePath = Path.GetFullPath(Path.Combine(directory, "extended-snapshot.json"));
                File.WriteAllText(requestPath,
                    "{\"schema_version\":\"1.0.0\",\"nonce\":\"extended\",\"response_path\":\""
                    + responsePath.Replace("\\", "/") + "\"}");
                EditorBridge.ExportRequestForTests(requestPath);
                SnapshotResult snapshot = JsonUtility.FromJson<SnapshotResult>(File.ReadAllText(responsePath));
                AssetResult ui = snapshot.assets.Single(asset => asset.path == folder + "/Panel.uxml");
                Assert.That(ui.kind, Is.EqualTo("ui_document"));
                Assert.That(ui.dependencies, Does.Contain(folder + "/Panel.uss"));
                AssetResult mat = snapshot.assets.Single(asset => asset.path == folder + "/Test.mat");
                Assert.That(mat.kind, Is.EqualTo("material"));
                Assert.That(mat.facts.Any(fact => fact.name == "property._Tint"), Is.True);
                AssetResult data = snapshot.assets.Single(asset => asset.path == folder + "/Custom.asset");
                Assert.That(data.kind, Is.EqualTo("asset"));
                Assert.That(data.references.Any(reference =>
                    reference.field == "icon" && reference.target == AssetPath
                    && reference.guid.Length == 32 && reference.local_id != 0), Is.True);
                Assert.That(data.facts.Any(fact =>
                    fact.name == "serialized.count" && fact.value == "7"), Is.True);
                Assert.That(data.subassets.Length, Is.GreaterThanOrEqualTo(1));
            }
            finally
            {
                AssetDatabase.DeleteAsset(folder);
            }
        }

        [Serializable]
        private sealed class SnapshotResult
        {
            public AssetResult[] assets;
        }

        [Serializable]
        private sealed class AssetResult
        {
            public string path;
            public string kind;
            public string[] dependencies;
            public FactResult[] facts;
            public ReferenceResult[] references;
            public SubassetResult[] subassets;
        }

        [Serializable]
        private sealed class FactResult
        {
            public string name;
            public string value;
        }

        [Serializable]
        private sealed class ReferenceResult
        {
            public string field;
            public string target;
            public string guid;
            public long local_id;
        }

        [Serializable]
        private sealed class SubassetResult
        {
            public long local_id;
        }

        [Test]
        public void RequestHandlerWritesImporterAndSubassetFacts()
        {
            string directory = Path.Combine("Library", "BetterContextEditorBridgeTests");
            Directory.CreateDirectory(directory);
            string requestPath = Path.GetFullPath(Path.Combine(directory, "request.json"));
            string responsePath = Path.GetFullPath(Path.Combine(directory, "snapshot.json"));
            string escapedResponse = responsePath.Replace("\\", "/");
            File.WriteAllText(
                requestPath,
                "{\"schema_version\":\"1.0.0\",\"bridge_version\":\"1.6.0\","
                + "\"nonce\":\"editmode\",\"source_hash\":\"source\","
                + "\"package_lock_hash\":\"packages\",\"response_path\":\""
                + escapedResponse
                + "\"}");

            EditorBridge.ExportRequestForTests(requestPath);

            string snapshot = File.ReadAllText(responsePath);
            StringAssert.Contains("\"nonce\": \"editmode\"", snapshot);
            StringAssert.Contains("\"path\": \"Assets/BetterContextEditorBridgeTest.png\"", snapshot);
            StringAssert.Contains("\"name\": \"pixels_per_unit\"", snapshot);
            StringAssert.Contains("\"type_name\": \"UnityEngine.Sprite\"", snapshot);
        }
    }
}
